"""Article endpoints: create/generate, list, read detail, inline edit, recheck, retry, publish.

Review UI backs onto these: editing persists immediately, `recheck` re-runs
SEO + checks after edits, `retry` re-queues generation for a failed article,
`publish` sends approved articles to Blogger.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import (
    ArticleDetailRead,
    ArticleImagesRead,
    ArticleRead,
    ArticleStartRead,
    ArticleUpdate,
    PublishRead,
    PublishRequest,
)
from db.base import get_db
from db.models import Article, BlogConnection, CheckResult, Image, PublishJob, Research
from pipeline.article.service import approve_article, create_article_from_research
from pipeline.images.status import IMAGE_STATUS_REJECTED, IMAGE_STATUS_SELECTED
from pipeline.research.service import STATUS_COMPLETE
from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    DRAFTED,
    DRAFTING,
    IMAGES_SEARCHING,
    IMAGE_READY,
    PUBLISH_FAILED,
    PUBLISHED,
    PUBLISHING,
    READY_FOR_REVIEW,
    SEO_DONE,
    transition,
)
from services.article_runner import (
    ensure_running,
    is_publish_running,
    is_running,
    start_background_article,
    start_background_images,
    start_background_publish,
    start_background_recheck,
)

router = APIRouter(prefix="/api/articles", tags=["articles"], dependencies=[Depends(require_local_token)])


def _get(db: Session, article_id: int) -> Article:
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


def _with_research(db: Session, article: Article) -> Research | None:
    if article.idea_id is None:
        return None
    return db.scalars(
        select(Research)
        .options()
        .where(Research.idea_id == article.idea_id)
        .order_by(Research.id.desc())
        .limit(1)
    ).first()


def _start_read(article: Article, cached: bool = False) -> ArticleStartRead:
    return ArticleStartRead(id=article.id, status=article.status, cached=cached)


@router.post("", response_model=ArticleStartRead, status_code=201)
def create_article_from_idea(idea_id: int, db: Session = Depends(get_db)) -> ArticleStartRead:
    """Create an article for an idea's completed research and start generation."""
    research = db.scalars(
        select(Research)
        .where(Research.idea_id == idea_id)
        .order_by(Research.id.desc())
        .limit(1)
    ).first()
    if research is None:
        raise HTTPException(status_code=409, detail="Run research for this idea first.")
    if research.status != STATUS_COMPLETE:
        raise HTTPException(status_code=409, detail="Wait for research to finish before drafting.")

    existing = db.scalars(
        select(Article).where(Article.idea_id == idea_id).order_by(Article.id.desc()).limit(1)
    ).first()
    if existing is not None:
        # Already drafted; don't create duplicates silently. Use retry/recheck
        # on the existing article instead.
        raise HTTPException(status_code=409, detail="An article already exists for this idea.")

    try:
        article = create_article_from_research(db, research)
    except IntegrityError:
        # Lost a concurrent create race for the same idea; re-use the winner.
        db.rollback()
        existing = db.scalars(
            select(Article).where(Article.idea_id == idea_id).order_by(Article.id.desc()).limit(1)
        ).first()
        if existing is None:
            raise
        start_background_article(existing.id)
        return _start_read(existing)
    start_background_article(article.id)
    return _start_read(article)


@router.get("", response_model=list[ArticleRead])
def list_articles(db: Session = Depends(get_db)) -> list[Article]:
    return list(db.scalars(select(Article).order_by(Article.created_at.desc())).all())


@router.get("/{article_id}", response_model=ArticleDetailRead)
def get_article(article_id: int, db: Session = Depends(get_db)) -> ArticleDetailRead:
    article = _get(db, article_id)
    # Lazy-resume a row left stuck in `drafting` by a crashed process (same
    # pattern as research rows), so it is never stuck behind a permanent spinner.
    if article.status == DRAFTING and not is_running(article_id):
        ensure_running(article_id)
    if article.status == IMAGES_SEARCHING and not is_running(article_id):
        # Lazy-resume a search left stuck by a crashed process.
        start_background_images(article_id)
    research = _with_research(db, article)
    return ArticleDetailRead.model_validate(article).model_copy(
        update={
            "summary_text": research.summary_text if research else None,
            "sources": [s for s in (research.sources if research else [])],
            "idea_title": article.idea.title if article.idea else None,
            "running": is_running(article_id),
        }
    )


@router.patch("/{article_id}", response_model=ArticleDetailRead)
def update_article(
    article_id: int, payload: ArticleUpdate, db: Session = Depends(get_db)
) -> ArticleDetailRead:
    """Inline edit: persist content changes. Edits that affect checks reset later stages."""
    article = _get(db, article_id)

    content_edited = False
    if payload.title is not None:
        article.title = payload.title
        content_edited = True
    if payload.body is not None:
        article.body = payload.body
        content_edited = True
    if payload.seo_title is not None:
        article.seo_title = payload.seo_title
        content_edited = True
    if payload.meta_description is not None:
        article.meta_description = payload.meta_description
        content_edited = True
    if payload.labels is not None:
        article.labels = payload.labels
    if payload.slug is not None:
        article.slug = payload.slug
        content_edited = True

    if content_edited and article.body:
        from pipeline.draft import count_words

        article.word_count = count_words(article.body)

    if content_edited and article.status in (
        SEO_DONE,
        CHECKED,
        IMAGES_SEARCHING,
        IMAGE_READY,
        READY_FOR_REVIEW,
        APPROVED,
    ):
        article.status = DRAFTED
        db.query(CheckResult).filter(CheckResult.article_id == article.id).delete()
    db.commit()
    return get_article(article_id, db)


@router.post("/{article_id}/recheck", response_model=ArticleDetailRead)
def recheck_article_endpoint(article_id: int, db: Session = Depends(get_db)) -> ArticleDetailRead:
    """Queue a SEO + checks re-run after manual edits."""
    article = _get(db, article_id)
    if not article.body:
        raise HTTPException(status_code=409, detail="No article content to check yet.")
    start_background_recheck(article_id)
    return get_article(article_id, db)


@router.post("/{article_id}/approve", response_model=ArticleDetailRead)
def approve_article_endpoint(article_id: int, db: Session = Depends(get_db)) -> ArticleDetailRead:
    """Human approval gate: checked -> ready_for_review -> approved.

    Records review_approved_at on approval. Publishing (Phase 5) requires the
    approved state; this is the product's human-review checkpoint.
    """
    article = _get(db, article_id)
    try:
        approve_article(db, article)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return get_article(article_id, db)


@router.post("/{article_id}/retry", response_model=ArticleStartRead)
def retry_article(article_id: int, db: Session = Depends(get_db)) -> ArticleStartRead:
    """Re-queue generation for a failed or stuck article."""
    article = _get(db, article_id)
    if article.status not in (DRAFT, DRAFTING):
        raise HTTPException(status_code=409, detail="Article is not in a retryable state.")
    start_background_article(article.id)
    return _start_read(article)


# --- Images ------------------------------------------------------------------


def _images_read(db: Session, article: Article) -> ArticleImagesRead:
    images = list(
        db.scalars(
            select(Image).where(Image.article_id == article.id).order_by(Image.id)
        ).all()
    )
    return ArticleImagesRead(
        article_id=article.id,
        status=article.status,
        running=is_running(article.id),
        images=images,
    )


def _assert_searchable(db: Session, article: Article) -> None:
    """Images may only be searched from checked / image_ready, one job at a time."""
    if article.status == IMAGES_SEARCHING or is_running(article.id):
        raise HTTPException(status_code=409, detail="A pipeline job for this article is already running.")
    if article.status not in (CHECKED, IMAGE_READY):
        raise HTTPException(
            status_code=409,
            detail=f"Images cannot be searched from status '{article.status}'",
        )


@router.get("/{article_id}/images", response_model=ArticleImagesRead)
def list_images(article_id: int, db: Session = Depends(get_db)) -> ArticleImagesRead:
    """List the article's image candidates/selection and the search status."""
    article = _get(db, article_id)
    return _images_read(db, article)


@router.post("/{article_id}/images/search", response_model=ArticleImagesRead, status_code=202)
def search_images(article_id: int, db: Session = Depends(get_db)) -> ArticleImagesRead:
    """Queue an image search (async). Returns the current image state."""
    article = _get(db, article_id)
    _assert_searchable(db, article)
    start_background_images(article.id)
    return _images_read(db, article)


@router.post("/{article_id}/images/retry", response_model=ArticleImagesRead, status_code=202)
def retry_images(article_id: int, db: Session = Depends(get_db)) -> ArticleImagesRead:
    """Re-queue a failed image search (alias of search for the retry UI)."""
    article = _get(db, article_id)
    _assert_searchable(db, article)
    start_background_images(article.id)
    return _images_read(db, article)


def _owned_image(db: Session, article: Article, image_id: int) -> Image:
    image = db.get(Image, image_id)
    if image is None or image.article_id != article.id:
        raise HTTPException(status_code=404, detail="Image not found for this article")
    return image


@router.post("/{article_id}/images/{image_id}/select", response_model=ArticleImagesRead)
def select_image(
    article_id: int, image_id: int, db: Session = Depends(get_db)
) -> ArticleImagesRead:
    """Select a candidate/suggested image. Never approves the article."""
    article = _get(db, article_id)
    image = _owned_image(db, article, image_id)
    if article.status == IMAGES_SEARCHING or is_running(article.id):
        raise HTTPException(
            status_code=409, detail="Image selection is unavailable while a search is running."
        )
    if image.status == IMAGE_STATUS_REJECTED:
        raise HTTPException(
            status_code=409,
            detail=f"This image was rejected and cannot be selected: {image.rejection_reason or 'rejected'}",
        )
    if image.status != IMAGE_STATUS_SELECTED:
        image.status = IMAGE_STATUS_SELECTED
        db.commit()
    return _images_read(db, article)


@router.delete("/{article_id}/images/{image_id}", response_model=ArticleImagesRead)
def remove_image(article_id: int, image_id: int, db: Session = Depends(get_db)) -> ArticleImagesRead:
    """Remove an image from the article entirely."""
    article = _get(db, article_id)
    image = _owned_image(db, article, image_id)
    if article.status == IMAGES_SEARCHING or is_running(article.id):
        raise HTTPException(
            status_code=409, detail="Images cannot be modified while a search is running."
        )
    db.delete(image)
    db.commit()
    return _images_read(db, article)


# --- Publishing (Phase 5E) ---------------------------------------------------


def _get_publish_connection(db: Session, article: Article) -> BlogConnection:
    """Fetch the blog connection or raise 400 if missing/disconnected."""
    if article.blog_id is None:
        raise HTTPException(status_code=400, detail="Article has no blog connection. Set a blog connection first.")
    conn = db.get(BlogConnection, article.blog_id)
    if conn is None or conn.status != "connected" or not conn.token_encrypted:
        raise HTTPException(status_code=400, detail="Blogger is not connected. Please connect your Blogger account.")
    return conn


def _assert_publishable(db: Session, article: Article) -> None:
    """Block concurrent publish jobs. Must be called before start_background_publish."""
    if article.status == PUBLISHING or is_publish_running(article.id):
        job = db.scalars(
            select(PublishJob).where(PublishJob.article_id == article.id).order_by(PublishJob.id.desc()).limit(1)
        ).first()
        job_id = job.id if job else None
        raise HTTPException(status_code=409, detail=f"A publish job is already running (job {job_id}).")


@router.post("/{article_id}/publish", response_model=PublishRead, status_code=202)
def publish_article(
    article_id: int, payload: PublishRequest = PublishRequest(), db: Session = Depends(get_db)
) -> PublishRead:
    """Publish an approved article to Blogger.

    Validates the approval gate, checks the Blogger connection, and submits
    a background publish job. Returns 202 with the article's publishing status.
    """
    article = _get(db, article_id)
    if article.status != APPROVED:
        raise HTTPException(status_code=409, detail=f"Article must be '{APPROVED}' to publish, current status is '{article.status}'.")
    _assert_publishable(db, article)
    _get_publish_connection(db, article)
    start_background_publish(article.id, as_draft=payload.as_draft)
    return PublishRead.model_validate(article)


@router.post("/{article_id}/publish/draft", response_model=PublishRead, status_code=202)
def save_as_draft(article_id: int, db: Session = Depends(get_db)) -> PublishRead:
    """Save an approved article as a Blogger draft (not publicly visible)."""
    article = _get(db, article_id)
    if article.status != APPROVED:
        raise HTTPException(status_code=409, detail=f"Article must be '{APPROVED}' to save as draft, current status is '{article.status}'.")
    _assert_publishable(db, article)
    _get_publish_connection(db, article)
    start_background_publish(article.id, as_draft=True)
    return PublishRead.model_validate(article)


@router.post("/{article_id}/publish/retry", response_model=PublishRead, status_code=202)
def retry_publish(article_id: int, db: Session = Depends(get_db)) -> PublishRead:
    """Retry publishing a failed article or re-publish/update an approved one.

    For PUBLISH_FAILED articles: re-approves before submitting.
    For APPROVED articles: submits directly (idempotent update if previously published).
    """
    article = _get(db, article_id)
    if article.status not in (APPROVED, PUBLISH_FAILED):
        raise HTTPException(status_code=409, detail=f"Article must be '{APPROVED}' or '{PUBLISH_FAILED}' to retry, current status is '{article.status}'.")
    if article.status == PUBLISH_FAILED:
        article.status = transition(PUBLISH_FAILED, APPROVED)
        db.commit()
    _assert_publishable(db, article)
    _get_publish_connection(db, article)
    start_background_publish(article.id, as_draft=False)
    return PublishRead.model_validate(article)
