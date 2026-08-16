"""Article orchestration: draft -> SEO -> checks with graceful degradation."""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import Article, CheckResult, Idea, Image, Research, Source as SourceRow
from pipeline.article.service import (
    approve_article,
    create_article_from_research,
    recheck_article,
    run_article_job,
)
from pipeline.images.providers.base import ImageProvider, ImageProviderError, ImageResult
from pipeline.images.status import (
    IMAGE_STATUS_CANDIDATE,
    IMAGE_STATUS_REJECTED,
    IMAGE_STATUS_SUGGESTED,
)
from pipeline.research.providers.base import Source
from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    DRAFTED,
    IMAGES_SEARCHING,
    IMAGE_READY,
    READY_FOR_REVIEW,
    SEO_DONE,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    """Keep the image stage network-free: no enabled providers by default."""
    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [])


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
    assert fresh.status == IMAGE_READY
    assert "Solar panels convert sunlight" in fresh.body
    assert fresh.word_count > 5
    assert fresh.seo_title == "Solar panels explained"
    assert fresh.labels == ["solar", "pv"]
    assert "images" in fresh.generation_errors  # no enabled providers -> no results
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
    assert fresh.status == IMAGE_READY
    assert fresh.body is not None
    assert fresh.seo_title  # deterministic fallback present
    assert len(db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all()) > 0


async def test_recheck_article_reruns_checks(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    await run_article_job(db, article, client=FakeClient())

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == IMAGE_READY
    original_checks = len(db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all())

    await recheck_article(db, fresh, client=FakeClient())
    fresh2 = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh2.status == CHECKED  # recheck is SEO + checks only, no image stage
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


async def test_approve_article_gate(db):
    """image_ready -> ready_for_review -> approved, with review_approved_at set."""
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    await run_article_job(db, article, client=FakeClient())
    article = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert article.status == IMAGE_READY

    approve_article(db, article)
    ready = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert ready.status == READY_FOR_REVIEW
    assert ready.review_approved_at is None

    approve_article(db, ready)
    approved = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert approved.status == APPROVED
    assert approved.review_approved_at is not None

    # Approving again is a no-op past the gate.
    approve_article(db, approved)
    final = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert final.status == APPROVED
    assert final.review_approved_at == approved.review_approved_at


async def test_approve_article_from_checked_skips_images(db):
    """The manual skip-images path (checked -> ready_for_review) still works."""
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    article.status = CHECKED  # e.g. after a recheck or a failed image search
    db.commit()

    approve_article(db, article)
    ready = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert ready.status == READY_FOR_REVIEW

    approve_article(db, ready)
    assert db.scalars(select(Article).where(Article.id == article.id)).one().status == APPROVED


async def test_approve_article_rejects_non_reviewable_state(db):
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    article.status = DRAFT
    db.commit()

    with pytest.raises(ValueError):
        approve_article(db, article)


# --- Image stage -------------------------------------------------------------


def _valid_result(title="Solar panel on roof", relevance=0.9) -> ImageResult:
    return ImageResult(
        provider="fake",
        image_url="https://upload.example.com/solar_panel.jpg",
        page_url="https://example.com/File:Sunlight_panel.jpg",
        title=title,
        description="A solar panel installation",
        thumb_url="https://upload.example.com/solar_panel_thumb.jpg",
        author="Jane Doe",
        license="CC0",
        license_url="https://example.com/cc0",
        attribution_required=False,
        mime="image/jpeg",
        width=1200,
        height=800,
        file_size=2048,
        relevance=relevance,
    )


class _FakeImageProvider(ImageProvider):
    name = "fake"
    display_name = "Fake"

    def __init__(self, results):
        self.results = results

    async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
        return self.results


def _checked_article(db, research):
    article = create_article_from_research(db, research)
    article.status = CHECKED
    db.commit()
    return article


async def test_image_stage_persists_suggested_candidates(db, monkeypatch):
    _, research = _seed_research(db)
    article = _checked_article(db, research)
    monkeypatch.setattr(
        "pipeline.images.service.enabled_providers",
        lambda: [_FakeImageProvider([_valid_result()])],
    )

    from pipeline.images.service import run_images_job

    await run_images_job(db, article)

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == IMAGE_READY
    rows = db.scalars(select(Image).where(Image.article_id == article.id).order_by(Image.id)).all()
    assert len(rows) == 1
    assert rows[0].status == IMAGE_STATUS_SUGGESTED
    assert rows[0].relevance == 0.9
    assert rows[0].mime == "image/jpeg"


async def test_image_stage_rejects_invalid_candidates_with_reason(db, monkeypatch):
    _, research = _seed_research(db)
    article = _checked_article(db, research)
    bad = _valid_result()
    bad = ImageResult(
        provider="fake",
        image_url=bad.image_url,
        page_url=bad.page_url,
        title="Non-commercial image",
        author="Jane Doe",
        license="CC BY-NC 4.0",
        mime="image/jpeg",
        relevance=0.9,
    )
    monkeypatch.setattr(
        "pipeline.images.service.enabled_providers",
        lambda: [_FakeImageProvider([bad])],
    )

    from pipeline.images.service import run_images_job

    await run_images_job(db, article)

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == IMAGE_READY  # usable, just no selectable images
    rows = db.scalars(select(Image).where(Image.article_id == article.id)).all()
    assert len(rows) == 1
    assert rows[0].status == IMAGE_STATUS_REJECTED
    assert "not allowed" in rows[0].rejection_reason


async def test_image_stage_provider_failure_degrades_to_checked(db, monkeypatch):
    _, research = _seed_research(db)
    article = _checked_article(db, research)

    class _Failing(ImageProvider):
        name = "failing"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            raise ImageProviderError("network error: ConnectError")

    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [_Failing()])

    from pipeline.images.service import run_images_job

    await run_images_job(db, article)

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == CHECKED
    assert "images" in fresh.generation_errors
    assert "network error" in fresh.generation_errors["images"]


async def test_image_stage_provider_failure_inside_article_job(db, monkeypatch):
    """A failing image stage never breaks the article job."""
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)

    class _Failing(ImageProvider):
        name = "failing"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            raise ImageProviderError("HTTP 500")

    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [_Failing()])

    await run_article_job(db, article, client=FakeClient())

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == CHECKED
    assert fresh.body is not None
    assert "images" in fresh.generation_errors
    assert len(db.scalars(select(CheckResult).where(CheckResult.article_id == article.id)).all()) > 0


async def test_stale_images_searching_row_restarts_cleanly(db, monkeypatch):
    """A row stuck in images_searching (crashed process) is resumed, not stuck."""
    _, research = _seed_research(db)
    article = create_article_from_research(db, research)
    article.status = IMAGES_SEARCHING
    db.commit()

    monkeypatch.setattr(
        "pipeline.images.service.enabled_providers",
        lambda: [_FakeImageProvider([_valid_result()])],
    )

    from pipeline.images.service import run_images_job

    await run_images_job(db, article)

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == IMAGE_READY
    assert len(db.scalars(select(Image).where(Image.article_id == article.id)).all()) == 1
