"""Background article runner: submits generation/recheck jobs to the shared serial runner."""

from __future__ import annotations

import logging

from db.base import SessionLocal
from pipeline.article.service import recheck_article, run_article_job
from pipeline.state import DRAFT
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
        if article.status in ("drafting", "drafted", "seo_done"):
            article.status = DRAFT
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


def _key(article_id: int) -> str:
    return f"article:{article_id}"


def _recheck_key(article_id: int) -> str:
    return f"article-recheck:{article_id}"


def start_background_article(article_id: int) -> None:
    """Queue an article generation run. No-op if already queued/running."""
    _runner_submit(_key(article_id), async_job(lambda: _run(article_id)))


def start_background_recheck(article_id: int) -> None:
    """Queue a SEO + checks re-run after manual edits."""
    _runner_submit(_recheck_key(article_id), async_job(lambda: _run_recheck(article_id)))


def is_running(article_id: int) -> bool:
    return _runner_is_running(_key(article_id)) or _runner_is_running(_recheck_key(article_id))
