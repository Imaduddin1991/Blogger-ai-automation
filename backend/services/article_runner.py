"""Background article runner: submits generation/recheck/image jobs to the shared serial runner."""

from __future__ import annotations

import logging

from db.base import SessionLocal
from pipeline.article.service import recheck_article, run_article_job
from pipeline.images.service import run_images_job
from pipeline.state import CHECKED, DRAFT, DRAFTED, DRAFTING, IMAGES_SEARCHING, IMAGE_READY, SEO_DONE
from services.runner import async_job, is_running as _runner_is_running, submit as _runner_submit

logger = logging.getLogger(__name__)


def _persist_failure(article_id: int, stage: str, exc: Exception) -> None:
    """Record a background job failure so the UI shows it instead of a silent hang."""
    db = SessionLocal()
    try:
        from db.models import Article

        article = db.get(Article, article_id)
        if article is None:
            return
        errors = dict(article.generation_errors or {})
        errors[stage] = f"{type(exc).__name__}: {exc}"
        article.generation_errors = errors
        if article.status in (DRAFTING, DRAFTED, SEO_DONE):
            article.status = DRAFT
        elif article.status == IMAGES_SEARCHING:
            # Unexpected image-job crash: return to a stable, usable state.
            article.status = CHECKED
        db.commit()
    except Exception:
        logger.exception("Failed to persist failure for article %s", article_id)
    finally:
        db.close()


async def _run(article_id: int) -> None:
    db = SessionLocal()
    try:
        from db.models import Article

        article = db.get(Article, article_id)
        if article is None:
            return
        await run_article_job(db, article)
    except Exception as exc:
        logger.exception("Article job %s failed", article_id)
        _persist_failure(article_id, "job", exc)
    finally:
        db.close()


async def _run_recheck(article_id: int) -> None:
    db = SessionLocal()
    try:
        from db.models import Article

        article = db.get(Article, article_id)
        if article is None:
            return
        await recheck_article(db, article)
    except Exception as exc:
        logger.exception("Article recheck %s failed", article_id)
        _persist_failure(article_id, "recheck", exc)
    finally:
        db.close()


async def _run_images(article_id: int) -> None:
    db = SessionLocal()
    try:
        from db.models import Article

        article = db.get(Article, article_id)
        if article is None:
            return
        # Manual image jobs only run from searchable states. If the article was
        # edited (now drafted) or a pipeline job moved it elsewhere while this
        # job sat queued, skip: never clobber an edit or re-draft an article.
        # IMAGES_SEARCHING is allowed so a stuck row resumes (run_images_job
        # restarts it internally).
        if article.status not in (CHECKED, IMAGE_READY, IMAGES_SEARCHING):
            return
        await run_images_job(db, article)
    except Exception as exc:
        logger.exception("Image job %s failed", article_id)
        _persist_failure(article_id, "images", exc)
    finally:
        db.close()


def _key(article_id: int) -> str:
    return f"article:{article_id}"


def _recheck_key(article_id: int) -> str:
    return f"article-recheck:{article_id}"


def _images_key(article_id: int) -> str:
    return f"article-images:{article_id}"


def start_background_article(article_id: int) -> None:
    """Queue an article generation run. No-op if already queued/running."""
    _runner_submit(_key(article_id), async_job(lambda: _run(article_id)))


def start_background_recheck(article_id: int) -> None:
    """Queue a SEO + checks re-run after manual edits."""
    _runner_submit(_recheck_key(article_id), async_job(lambda: _run_recheck(article_id)))


def start_background_images(article_id: int) -> None:
    """Queue a manual image search/re-search. No-op if already queued/running."""
    _runner_submit(_images_key(article_id), async_job(lambda: _run_images(article_id)))


def ensure_running(article_id: int) -> None:
    """Resume a stale in-flight run (e.g. after a restart)."""
    start_background_article(article_id)


def is_running(article_id: int) -> bool:
    return (
        _runner_is_running(_key(article_id))
        or _runner_is_running(_recheck_key(article_id))
        or _runner_is_running(_images_key(article_id))
    )
