"""Research orchestration service: cache, persistence, graceful degradation.

Uses an in-memory SQLite engine and fakes for the providers + Ollama, so no
network and no model are required.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import Idea, Research, Source as SourceRow
from pipeline.research.providers.base import Source
from pipeline.research.service import (
    STATUS_COMPLETE,
    STATUS_RESEARCHING,
    create_research,
    run_research_job,
    topic_key,
)


@pytest.fixture
def db():
    """Fresh in-memory SQLite per test (topic-key cache must not leak)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


@pytest.fixture
def idea(db):
    row = Idea(title="Why solar panels work", prompt="nope")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class FakeProvider:
    name = "fake"

    async def search(self, topic, limit=5):
        return [
            Source(provider=self.name, title=f"{topic} A", url="https://example.com/a", snippet="snippet a"),
            Source(provider=self.name, title=f"{topic} B", url="https://example.com/b", snippet="snippet b"),
        ]


class FakeClient:
    def __init__(self, available: bool = True):
        self.available = available

    async def chat(self, messages, *, model=None, format=None, options=None, timeout=None):
        return "Summary text here.\n\nKEY POINTS:\n- p1\n- p2"


def test_topic_key_stable_and_case_insensitive():
    assert topic_key("  Solar Panels ") == topic_key("solar panels")
    assert len(topic_key("x")) == 64


def test_create_research_persists_and_returns_researching(db, idea):
    research = create_research(db, idea.id, idea.title)
    assert research.status == STATUS_RESEARCHING
    assert research.topic == idea.title
    assert db.get(Research, research.id) is not None


async def test_create_research_returns_cache_hit_on_complete(db, idea, monkeypatch):
    monkeypatch.setattr(
        "pipeline.research.service.run_research",
        _fake_run_research,
    )
    first = create_research(db, idea.id, idea.title)
    await run_research_job(db, first, topic=idea.title, client=FakeClient())
    second = create_research(db, idea.id, idea.title)
    assert second.id == first.id
    assert second.status == STATUS_COMPLETE


def test_create_research_reuses_inflight_run(db, idea):
    first = create_research(db, idea.id, idea.title)
    second = create_research(db, idea.id, idea.title)
    assert second.id == first.id


async def test_run_research_job_persists_sources_and_summary(db, idea, monkeypatch):
    monkeypatch.setattr("pipeline.research.service.run_research", _fake_run_research)
    research = create_research(db, idea.id, idea.title)
    await run_research_job(db, research, topic=idea.title, client=FakeClient())

    fresh = db.scalars(select(Research).where(Research.id == research.id)).one()
    assert fresh.status == STATUS_COMPLETE
    assert fresh.coverage == 1.0
    assert fresh.providers_used == ["fake"]
    assert "Summary text here" in fresh.summary_text
    sources = db.scalars(select(SourceRow).where(SourceRow.research_id == research.id)).all()
    assert len(sources) == 2
    assert {s.url for s in sources} == {"https://example.com/a", "https://example.com/b"}


async def test_run_research_job_records_provider_errors_and_keeps_going(db, idea, monkeypatch):
    async def all_providers_failed(topic, limit=5):
        from pipeline.research import ResearchOutput

        return ResearchOutput(
            topic=topic,
            sources=[],
            provider_errors=[("fake", "provider down")],
            providers_attempted=["fake"],
        )

    monkeypatch.setattr("pipeline.research.service.run_research", all_providers_failed)
    research = create_research(db, idea.id, idea.title)
    await run_research_job(db, research, topic=idea.title, client=FakeClient())
    fresh = db.scalars(select(Research).where(Research.id == research.id)).one()
    assert fresh.status == STATUS_COMPLETE
    assert fresh.coverage == 0.0
    assert fresh.provider_errors == {"fake": "provider down"}


async def test_run_research_job_without_summary_still_completes(db, idea, monkeypatch):
    """Ollama unavailable must not lose sources: summary stays None, run completes."""

    class UnavailableClient(FakeClient):
        async def chat(self, *a, **k):
            from services.ollama_client import OllamaUnavailableError

            raise OllamaUnavailableError("ollama down")

    monkeypatch.setattr("pipeline.research.service.run_research", _fake_run_research)
    research = create_research(db, idea.id, idea.title)
    await run_research_job(db, research, topic=idea.title, client=UnavailableClient())
    fresh = db.scalars(select(Research).where(Research.id == research.id)).one()
    assert fresh.status == STATUS_COMPLETE
    assert fresh.summary_text is None
    assert "summarize" in fresh.provider_errors
    assert len(db.scalars(select(SourceRow).where(SourceRow.research_id == research.id)).all()) == 2


async def _fake_run_research(topic, limit=5, providers=None):
    return await _fake_output(topic)


async def _fake_output(topic):
    from pipeline.research import ResearchOutput

    return ResearchOutput(
        topic=topic,
        sources=[
            Source(provider="fake", title=f"{topic} A", url="https://example.com/a", snippet="snippet a"),
            Source(provider="fake", title=f"{topic} B", url="https://example.com/b", snippet="snippet b"),
        ],
        providers_attempted=["fake"],
    )
