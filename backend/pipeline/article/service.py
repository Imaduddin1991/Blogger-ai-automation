"""Article pipeline orchestration: draft -> SEO -> checks.

Sits between the API layer and the pure stage modules (`pipeline.draft`,
`pipeline.seo`, `pipeline.checks`). Drives the Article state machine, persists
every stage before moving on (resumable), and degrades gracefully: a failed
draft leaves the article retryable with a recorded error; SEO always has a
deterministic fallback; checks are rule-based and always run.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from db.models import Article, CheckResult, Idea, Research
from pipeline.checks import run_all_checks
from pipeline.draft import ArticleDraft, count_words, generate_draft
from pipeline.research.providers.base import Source
from pipeline.seo import build_slug, generate_seo_metadata
from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    DRAFTED,
    DRAFTING,
    IMAGE_READY,
    READY_FOR_REVIEW,
    SEO_DONE,
    transition,
)
from services.ollama_client import OllamaClient, OllamaUnavailableError

# Mirrors the ArticleUpdate API schema limits so LLM output is constrained at
# the same boundary the UI is. Keeps a poisoned/model output from persisting
# unbounded text or control characters into the DB.
MAX_TITLE = 300
MAX_BODY = 200_000
MAX_SLUG = 500
MAX_SEO_TITLE = 200
MAX_META_DESCRIPTION = 2000
MAX_LABELS = 5
MAX_LABEL_LENGTH = 50
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(text: str | None, max_len: int) -> str:
    """Strip control characters (keep newlines/tabs) and cap length."""
    return _CONTROL_CHARS.sub("", text or "")[:max_len]


def _with_detail(db: Session, article: Article) -> Article:
    return db.scalars(
        select(Article)
        .options(selectinload(Article.check_results))
        .where(Article.id == article.id)
    ).one()


def _research_for(db: Session, article: Article) -> Research | None:
    if article.idea_id is None:
        return None
    return db.scalars(
        select(Research)
        .where(Research.idea_id == article.idea_id)
        .order_by(Research.id.desc())
        .limit(1)
    ).first()


def _sources(research: Research | None) -> list[Source]:
    if research is None:
        return []
    return [
        Source(
            provider=s.provider,
            title=s.title,
            url=s.url,
            snippet=s.snippet,
            relevance=s.relevance,
            license=s.license,
        )
        for s in research.sources
    ]


def create_article_from_research(db: Session, research: Research) -> Article:
    """Create an article for an idea's research (starts at `draft`)."""
    topic = research.topic or (research.idea.title if research.idea else "")
    article = Article(
        idea_id=research.idea_id,
        title=topic,
        slug=build_slug(topic),
        status=DRAFT,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def _set_error(db: Session, article: Article, stage: str, message: str) -> None:
    article.generation_errors = {**(article.generation_errors or {}), stage: message}
    db.commit()


def _apply_draft(db: Session, article: Article, draft: ArticleDraft) -> None:
    # Re-read the row so a concurrent inline edit to a field this stage does
    # not own (e.g. SEO metadata) isn't clobbered by this stale-object commit.
    db.refresh(article)
    errors = dict(article.generation_errors or {})
    errors.pop("draft", None)
    article.generation_errors = errors
    article.title = _clean_text(draft.title, MAX_TITLE)
    article.body = _clean_text(draft.body_markdown, MAX_BODY)
    article.word_count = count_words(article.body)
    article.status = transition(article.status, DRAFTED)
    db.commit()


async def _draft_stage(db: Session, article: Article, client) -> bool:
    research = _research_for(db, article)
    if research is None:
        _set_error(db, article, "draft", "No research found for this article.")
        return False
    notes = research.idea.prompt if research.idea else None
    try:
        draft = await generate_draft(
            research.topic or article.title or "",
            research.summary_text,
            _sources(research),
            client,
            notes=notes,
        )
    except OllamaUnavailableError as exc:
        _set_error(db, article, "draft", f"Ollama unavailable: {exc}")
        return False
    except Exception as exc:
        _set_error(db, article, "draft", f"Draft generation failed: {exc}")
        return False
    _apply_draft(db, article, draft)
    return True


async def _seo_stage(db: Session, article: Article, client) -> None:
    db.refresh(article)
    research = _research_for(db, article)
    topic = research.topic if research else article.title or ""
    meta = await generate_seo_metadata(
        topic, article.title or "", article.body or "", client
    )
    article.seo_title = _clean_text(meta.seo_title, MAX_SEO_TITLE)
    article.meta_description = _clean_text(meta.meta_description, MAX_META_DESCRIPTION)
    article.labels = [_clean_text(lbl, MAX_LABEL_LENGTH) for lbl in meta.labels][:MAX_LABELS]
    article.slug = _clean_text(
        article.slug or build_slug(article.title or ""), MAX_SLUG
    )
    if article.status == DRAFTED:
        article.status = transition(article.status, SEO_DONE)
    db.commit()


def _checks_stage(db: Session, article: Article) -> None:
    db.refresh(article)
    research = _research_for(db, article)
    topic = research.topic if research else article.title or ""
    results = run_all_checks(
        article.body or "",
        title=article.title or "",
        seo_title=article.seo_title,
        meta_description=article.meta_description,
        slug=article.slug,
        topic=topic,
    )
    db.query(CheckResult).filter(CheckResult.article_id == article.id).delete()
    db.add_all(
        [
            CheckResult(
                article_id=article.id,
                check_type=r["check_type"],
                passed=r["passed"],
                severity=r["severity"],
                message=r["message"],
                details=r["details"],
            )
            for r in results
        ]
    )
    if article.status == SEO_DONE:
        article.status = transition(article.status, CHECKED)
    db.commit()


async def run_article_job(db: Session, article: Article, *, client=None) -> Article:
    """Run draft -> SEO -> checks for an article. Returns the article."""
    if article.status == DRAFTING:
        # Stuck in-flight row from a crashed process; retry re-runs from scratch.
        article.status = DRAFT
    article.status = transition(article.status, DRAFTING)
    db.commit()

    client = client or OllamaClient()
    if not await _draft_stage(db, article, client):
        article.status = DRAFT
        db.commit()
        return _with_detail(db, article)

    await _seo_stage(db, article, client)
    _checks_stage(db, article)
    return _with_detail(db, article)


async def recheck_article(db: Session, article: Article, *, client=None) -> Article:
    """Re-run SEO + checks after edits (idempotent, no draft regeneration)."""
    client = client or OllamaClient()
    if article.status in (SEO_DONE, CHECKED, DRAFTED, IMAGE_READY, READY_FOR_REVIEW, APPROVED):
        article.status = DRAFTED
        db.commit()
    await _seo_stage(db, article, client)
    _checks_stage(db, article)
    return _with_detail(db, article)


def approve_article(db: Session, article: Article) -> Article:
    """Human approval gate: checked/article-ready -> ready_for_review -> approved.

    Records `review_approved_at` on first approval. Phase 5 will require
    `approved` before any publish job is created.
    """
    db.refresh(article)
    if article.status == APPROVED:
        return _with_detail(db, article)  # already approved; idempotent
    if article.status not in (CHECKED, READY_FOR_REVIEW):
        raise ValueError(
            f"Article cannot be approved from status '{article.status}'"
        )
    if article.status == CHECKED:
        article.status = transition(article.status, READY_FOR_REVIEW)
    else:
        article.status = transition(article.status, APPROVED)
        article.review_approved_at = datetime.now(timezone.utc)
    db.commit()
    return _with_detail(db, article)


def article_summary_counts(db: Session, article_id: int) -> dict[str, int]:
    """Pass/fail counts per check type, for badges."""
    rows = db.execute(
        select(CheckResult.check_type, CheckResult.passed).where(
            CheckResult.article_id == article_id
        )
    ).all()
    counts: dict[str, int] = {"total": len(rows), "passed": 0, "failed": 0}
    for check_type, passed in rows:
        counts[check_type] = counts.get(check_type, 0) + 1
        if passed:
            counts["passed"] += 1
        else:
            counts["failed"] += 1
    return counts
