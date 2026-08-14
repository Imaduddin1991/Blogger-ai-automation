"""Research orchestration: cache by topic hash + persistence + summarization.

Sits between the pure provider gathering (`pipeline.research.run_research`)
and the API layer. Owns the Research/Source rows so the pipeline is durable
and resumable: every stage persists before moving on.

Statuses: researching -> complete | error. A cache hit (same topic_key with
status complete) short-circuits a fresh run; re-research is explicit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from db.models import Idea, Research, Source as SourceRow
from pipeline.research import run_research
from pipeline.research.providers.base import Source
from pipeline.summarize import summarize_research
from services.ollama_client import OllamaClient, OllamaUnavailableError

STATUS_RESEARCHING = "researching"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"


class Summarizer(Protocol):
    """Minimal client surface used by the research job (duck-typed)."""

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        format: str | None = None,
        options: dict | None = None,
        timeout: float | None = None,
    ) -> str: ...


@dataclass
class ResearchResult:
    research: Research
    status: str


def topic_key(topic: str) -> str:
    """Stable cache key for a topic (case-insensitive, whitespace-folded)."""
    return hashlib.sha256(" ".join((topic or "").strip().lower().split()).encode("utf-8")).hexdigest()


def _with_sources(db: Session, research: Research) -> Research:
    return db.scalars(
        select(Research).options(selectinload(Research.sources)).where(Research.id == research.id)
    ).one()


def create_research(db: Session, idea_id: int, topic: str, *, limit: int = 5) -> Research:
    """Create a research run for an idea, or return a completed cache hit.

    Unique topic_key makes concurrent/duplicate submissions safe: an
    in-flight or completed run for the same topic is reused.
    """
    key = topic_key(topic)
    existing = db.scalars(
        select(Research)
        .options(selectinload(Research.sources))
        .where(Research.topic_key == key)
        .order_by(Research.id.desc())
        .limit(1)
    ).first()
    if existing is not None and existing.status == STATUS_COMPLETE:
        return existing

    if existing is None:
        research = Research(
            idea_id=idea_id,
            topic=topic,
            topic_key=key,
            status=STATUS_RESEARCHING,
        )
        db.add(research)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # lost a race; someone else owns this topic
            research = db.scalars(
                select(Research)
                .options(selectinload(Research.sources))
                .where(Research.topic_key == key)
                .order_by(Research.id.desc())
                .limit(1)
            ).first()
            if research is None:
                raise
    else:
        # An in-flight run exists; reuse it (do not duplicate the topic).
        research = _with_sources(db, existing)
    db.refresh(research)
    return research


async def run_research_job(
    db: Session,
    research: Research,
    *,
    topic: str | None = None,
    limit: int = 5,
    client: Summarizer | None = None,
) -> Research:
    """Execute one research run: providers -> persist sources -> summarize.

    Graceful degradation: a provider failure is recorded, not fatal; an
    unavailable Ollama still leaves sources persisted with summary=None.
    """
    research.status = STATUS_RESEARCHING
    db.commit()

    output = await run_research(topic or research.topic or "", limit=limit)

    research.sources = [
        SourceRow(
            provider=s.provider,
            title=s.title,
            url=s.url,
            snippet=s.snippet,
            relevance=s.relevance,
            license=s.license,
        )
        for s in output.sources
    ]
    research.providers_used = output.providers_attempted
    research.provider_errors = {name: err for name, err in output.provider_errors} or None
    research.coverage = output.coverage
    db.commit()

    if output.sources:
        try:
            client = client or OllamaClient()
            summary = await summarize_research(
                topic or research.topic or "",
                output.sources,
                client,
            )
            research.summary_text = summary.summary_text
        except OllamaUnavailableError as exc:
            research.provider_errors = {**(research.provider_errors or {}), "summarize": str(exc)}
        except Exception as exc:  # model-level failure: keep sources, record error
            research.provider_errors = {**(research.provider_errors or {}), "summarize": str(exc)}

    research.status = STATUS_COMPLETE
    db.commit()
    db.refresh(research)
    return _with_sources(db, research)


def research_topic(db: Session, research_id: int) -> str:
    """Resolve a research run's topic from its linked idea (fallback: stored)."""
    research = db.get(Research, research_id)
    if research is None:
        return ""
    if research.topic:
        return research.topic
    if research.idea_id:
        idea = db.get(Idea, research.idea_id)
        if idea is not None:
            return idea.title
    return ""
