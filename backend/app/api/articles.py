"""Article endpoints: create/generate, list, read detail, inline edit, recheck, retry.

Review UI backs onto these: editing persists immediately, `recheck` re-runs
SEO + checks after edits, `retry` re-queues generation for a failed article.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import (
    ArticleDetailRead,
    ArticleRead,
    ArticleStartRead,
    ArticleUpdate,
)
from db.base import get_db
from db.models import Article, CheckResult, Research
from pipeline.article.service import approve_article, create_article_from_research
from pipeline.research.service import STATUS_COMPLETE
from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    DRAFTED,
    DRAFTING,
    IMAGE_READY,
    READY_FOR_REVIEW,
    SEO_DONE,
)
from services.article_runner import (
    ensure_running,
    is_running,
    start_background_article,
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
