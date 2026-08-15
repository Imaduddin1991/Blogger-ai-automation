"""Article orchestration: draft -> SEO -> checks with graceful degradation."""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import Article, CheckResult, Idea, Research, Source as SourceRow
from pipeline.article.service import (
    create_article_from_research,
    recheck_article,
    run_article_job,
)
from pipeline.research.providers.base import Source
from pipeline.state import CHECKED, DRAFT, DRAFTED, SEO_DONE


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


def _seed_research(db):
    idea = Idea(title="Why solar panels work", prompt="Keep it friendly")
    db.add(idea)
    db.flush()
    research = Research(idea_id=idea.id, topic=idea.title, topic_key="key", status="complete")
    db.add(research)
    db.flush()
    db.add(
        SourceRow(
            research_id=research.id,
            provider="fake",
            title="Solar basics",
            url="https://example.com/a",
            snippet="PV cells make electricity",
        )
    )
    db.commit()
    return idea, research


class FakeClient:
    def __init__(self, draft_ok: bool = True, seo_ok: bool = True):
        self.draft_ok = draft_ok
        self.seo_ok = seo_ok

    async def chat(self, messages, *, model=None, format=None, options=None, timeout=None):
        if not self.draft_ok:
            from services.ollama_client import OllamaUnavailableError

            raise OllamaUnavailableError("ollama down")
        if format == "json":
            if not self.seo_ok:
                from services.ollama_client import OllamaUnavailableError

                raise OllamaUnavailableError("ollama down")
            return (
                '{"seo_title": "Solar panels explained", '
                '"meta_description": "How PV cells convert sunlight to electricity.", '
                '"labels": ["solar", "pv"]}'
            )
        return (
            "TITLE: Why solar panels work\nBODY:\n"
            "## Introduction\n\nSolar panels convert sunlight into electricity. "
            "## Costs\n\nPrices have fallen over the past decade."
        )


def test_create_article_from_research(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    assert article.status == DRAFT
    assert article.title == research.topic
    assert article.slug == "why-solar-panels-work"


async def test_run_article_job_full_pipeline(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)

    await run_article_job(db, article, client=FakeClient())

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == CHECKED
    assert "Solar panels convert sunlight" in fresh.body
    assert fresh.word_count > 5
    assert fresh.seo_title == "Solar panels explained"
    assert fresh.labels == ["solar", "pv"]
    assert fresh.generation_errors == {}
    checks = db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all()
    assert len(checks) > 10
    assert {c.check_type for c in checks} == {"seo", "quality", "policy", "repetition"}


async def test_run_article_job_ollama_down_keeps_retryable(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)

    await run_article_job(db, article, client=FakeClient(draft_ok=False))

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == DRAFT
    assert fresh.body is None
    assert "draft" in fresh.generation_errors
    assert db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).first() is None


async def test_run_article_job_seo_failure_falls_back(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)

    await run_article_job(db, article, client=FakeClient(seo_ok=False))

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == CHECKED
    assert fresh.body is not None
    assert fresh.seo_title  # deterministic fallback present
    assert len(db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all()) > 0


async def test_recheck_article_reruns_checks(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    await run_article_job(db, article, client=FakeClient())

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == CHECKED
    original_checks = len(db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all())

    await recheck_article(db, fresh, client=FakeClient())
    fresh2 = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh2.status == CHECKED
    new_checks = db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all()
    assert len(new_checks) == original_checks
    assert all(c.article_id == article.id for c in new_checks)


async def test_recheck_article_from_drafted_runs_seo_and_checks(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    await run_article_job(db, article, client=FakeClient())

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    fresh.status = DRAFTED  # simulate a manual edit resetting later stages
    db.commit()

    await recheck_article(db, fresh, client=FakeClient())
    fresh2 = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh2.status == CHECKED
    assert fresh2.seo_title
