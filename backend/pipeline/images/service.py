"""Image pipeline orchestration + data-layer helpers (Phase 4C/4D).

4C owns the pure mapping/persistence: converts a validated provider record
into an `Image` row. 4D adds the orchestration the pipeline and API need:
deterministic query generation from article data, the search run that
persists candidate/rejected rows, and the resumable image stage job
(`run_images_job`) that drives `CHECKED/IMAGE_READY -> images_searching ->
image_ready`, degrading to `CHECKED` on provider failure so the article stays
fully usable. Images are optional in every path; no image bytes are ever
downloaded (URL + metadata only).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Article, Image, Research
from pipeline.images.dedupe import dedupe_candidates
from pipeline.images.providers.base import ImageProvider, ImageProviderError, ImageResult
from pipeline.images.providers.registry import enabled_providers
from pipeline.images.query import generate_image_queries
from pipeline.images.relevance import MIN_RELEVANCE
from pipeline.images.status import (
    IMAGE_STATUS_CANDIDATE,
    IMAGE_STATUS_REJECTED,
    IMAGE_STATUS_SELECTED,
    IMAGE_STATUS_SUGGESTED,
)
from pipeline.images.validate import validate_image_metadata
from pipeline.state import CHECKED, IMAGE_READY, IMAGES_SEARCHING, transition

# Per-query provider limit. The MVP never fetches more than this from one
# provider/query; query generation produces 1-3 queries.
_QUERY_LIMIT = 8

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$", re.MULTILINE)


def _latest_research(db: Session, article: Article) -> Research | None:
    if article.idea_id is None:
        return None
    return db.scalars(
        select(Research)
        .where(Research.idea_id == article.idea_id)
        .order_by(Research.id.desc())
        .limit(1)
    ).first()


def image_queries_for_article(db: Session, article: Article) -> list[str]:
    """Deterministic search queries from the article's own data (no LLM).

    Term priority: research topic, article title, first three body headings,
    first three research source titles — mirroring the approved plan.
    """
    research = _latest_research(db, article)
    topic = research.topic if research else (article.title or "")
    headings = tuple(m.strip() for m in _HEADING_RE.findall(article.body or ""))
    research_terms = tuple(s.title for s in (research.sources if research else [])[:3])
    return generate_image_queries(topic, article.title or "", headings, research_terms)


def image_result_to_row(result: ImageResult, *, article_id: int | None = None) -> Image:
    """Map a provider record to a persisted `Image` row.

    Runs the full validation layer first; an unusable candidate raises
    ValueError with the rejection reasons instead of persisting.
    """
    problems = validate_image_metadata(result)
    if problems:
        raise ValueError("; ".join(problems))
    return Image(
        article_id=article_id,
        provider=result.provider,
        url=result.image_url,
        page_url=result.page_url,
        caption=result.title or None,
        alt=result.description or None,
        attribution=None,  # rendered credit line is built at render time
        license=result.license or None,
        license_url=result.license_url or None,
        author=result.author or None,
        attribution_required=result.attribution_required,
        usage_notes=result.usage_notes or None,
        thumb_url=result.thumb_url or None,
        mime=result.mime or None,
        width=result.width,
        height=result.height,
        file_size=result.file_size,
        relevance=result.relevance,
        retrieved_at=result.retrieved_at or datetime.now(timezone.utc),
        status=IMAGE_STATUS_CANDIDATE,
    )


def image_result_to_rejected(result: ImageResult, *, article_id: int | None = None, reason: str) -> Image:
    """Map a provider record that failed validation to a persisted `rejected` row.

    Kept with a visible `rejection_reason` so the UI can explain why a
    candidate was discarded (e.g. non-commercial license, missing attribution).
    Only safe, already-validated URL/license fields are stored.
    """
    return Image(
        article_id=article_id,
        provider=result.provider,
        url=result.image_url,
        page_url=result.page_url,
        caption=result.title or None,
        alt=result.description or None,
        license=result.license or None,
        license_url=result.license_url or None,
        author=result.author or None,
        usage_notes=result.usage_notes or None,
        status=IMAGE_STATUS_REJECTED,
        rejection_reason=reason,
        relevance=result.relevance,
        retrieved_at=result.retrieved_at or datetime.now(timezone.utc),
    )


async def run_image_search(
    db: Session,
    article: Article,
    *,
    providers: list[ImageProvider] | None = None,
) -> tuple[list[Image], list[str], int]:
    """Run the image search for an article and persist the results.

    Returns `(persisted_candidates, provider_errors, filtered_count)`:
      - valid, relevant results persist as `candidate` rows (best one is then
        marked `suggested` by the caller),
      - invalid results persist as `rejected` rows with the stored reason,
      - off-topic results (below MIN_RELEVANCE) are dropped and only counted.

    Raises ImageProviderError when providers were attempted but no usable
    candidate survived (article stays usable: caller degrades to CHECKED).
    A fresh search clears the previous search's non-selected rows; rows the
    human already selected are preserved. Never fetches image bytes.
    """
    providers = providers if providers is not None else enabled_providers()

    db.query(Image).filter(
        Image.article_id == article.id,
        Image.status != IMAGE_STATUS_SELECTED,
    ).delete()
    db.commit()

    queries = image_queries_for_article(db, article)
    if not queries:
        return [], [], 0

    results: list[ImageResult] = []
    provider_errors: list[str] = []
    for provider in providers:
        for query in queries:
            try:
                results.extend(await provider.search(query, limit=_QUERY_LIMIT))
            except ImageProviderError as exc:
                provider_errors.append(f"{provider.name}: {exc}")
            except Exception as exc:
                provider_errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")

    candidates: list[Image] = []
    filtered = 0
    for result in dedupe_candidates(results):
        problems = validate_image_metadata(result)
        if problems:
            db.add(
                image_result_to_rejected(
                    result, article_id=article.id, reason="; ".join(problems)
                )
            )
            continue
        if result.relevance < MIN_RELEVANCE:
            filtered += 1
            continue
        row = image_result_to_row(result, article_id=article.id)
        db.add(row)
        candidates.append(row)

    if not candidates and provider_errors:
        raise ImageProviderError("; ".join(provider_errors))

    db.commit()
    if candidates:
        best = max(candidates, key=lambda r: (r.relevance, r.id))
        best.status = IMAGE_STATUS_SUGGESTED
        db.commit()
    return candidates, provider_errors, filtered


async def run_images_job(db: Session, article: Article) -> Article:
    """Image stage: `CHECKED/IMAGE_READY -> images_searching -> image_ready`.

    Runs inline as the last step of the article job and as the manual
    re-search/retry job. A provider failure degrades to `CHECKED` with
    `generation_errors["images"]` set (article stays fully usable and can
    skip images or retry); zero usable results still reaches `image_ready`
    with an informational note. A stale in-flight row (crashed process) is
    restarted cleanly.
    """
    db.refresh(article)
    if article.status == IMAGES_SEARCHING:
        article.status = transition(article.status, CHECKED)  # stuck row: restart
    article.status = transition(article.status, IMAGES_SEARCHING)
    db.commit()

    errors = dict(article.generation_errors or {})
    try:
        candidates, provider_errors, filtered = await run_image_search(db, article)
    except ImageProviderError as exc:
        # Only degrade to CHECKED if the article is still mid-search; a user
        # edit that landed meanwhile (status already changed in the DB) wins.
        errors["images"] = f"image search failed: {exc}"
        db.execute(
            select(Article)
            .where(Article.id == article.id)
            .execution_options(populate_existing=True)
        ).scalar_one()
        if article.status == IMAGES_SEARCHING:
            article.status = transition(article.status, CHECKED)
        article.generation_errors = errors
        db.commit()
        return article

    if not candidates:
        if filtered:
            errors["images"] = f"no usable images: {filtered} result(s) filtered as irrelevant"
        else:
            errors["images"] = "no usable images: no image results"
    else:
        errors.pop("images", None)
    article.generation_errors = errors
    # Re-read the authoritative status before the final transition: if the
    # human edited the article while the search ran (status is no longer
    # images_searching in the DB), persist the images but never clobber the
    # edit.
    db.execute(
        select(Article)
        .where(Article.id == article.id)
        .execution_options(populate_existing=True)
    ).scalar_one()
    if article.status == IMAGES_SEARCHING:
        article.status = transition(article.status, IMAGE_READY)
    db.commit()
    return article

