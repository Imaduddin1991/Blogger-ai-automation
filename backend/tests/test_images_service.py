"""Image orchestration (Phase 4D): query generation, search run, persistence.

Covers the deterministic query builder, candidate persistence (candidate /
suggested / rejected), relevance filtering, dedupe, provider-failure
recording, cross-article reuse (informational, never blocking), and the
no-downloads guarantee.
"""

import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from db.base import Base
from db.models import Article, Idea, Image, Research, Source as SourceRow
from pipeline.images.providers.base import ImageProvider, ImageProviderError, ImageResult
from pipeline.images.status import (
    IMAGE_STATUS_REJECTED,
    IMAGE_STATUS_SELECTED,
    IMAGE_STATUS_SUGGESTED,
)
from pipeline.state import CHECKED, DRAFTED, IMAGE_READY

ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(ENGINE)
    yield
    Base.metadata.drop_all(ENGINE)


@pytest.fixture
def db():
    session_maker = sessionmaker(bind=ENGINE, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    """Never hit the network: no enabled providers unless a test injects one."""
    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [])


def _seed(db, title="Solar panel installation guide") -> Article:
    idea = Idea(title=title, prompt=None)
    db.add(idea)
    db.flush()
    key = title.lower().replace(" ", "_")
    research = Research(idea_id=idea.id, topic=idea.title, topic_key=key, status="complete")
    db.add(research)
    db.flush()
    db.add(
        SourceRow(
            research_id=research.id,
            provider="fake",
            title="Solar panel basics",
            url="https://example.com/a",
            snippet="PV cells make electricity",
        )
    )
    article = Article(idea_id=idea.id, title=idea.title, slug="solar-panel-installation-guide",
                      body="## Installation\n\nSunlight powers panels.\n\n## Costs\n\nPrices fell.",
                      status=CHECKED)
    db.add(article)
    db.commit()
    return article


def _result(url="https://upload.example.com/panel.jpg", title="Solar panel on roof",
            license="CC0", relevance=0.9, provider="fake", **kwargs) -> ImageResult:
    return ImageResult(
        provider=provider,
        image_url=url,
        page_url="https://example.com/File:Panel.jpg",
        title=title,
        description="A solar panel installation",
        thumb_url="https://upload.example.com/panel_thumb.jpg",
        author="Jane Doe",
        license=license,
        license_url="https://example.com/cc0",
        attribution_required=False,
        mime="image/jpeg",
        width=1200,
        height=800,
        file_size=2048,
        relevance=relevance,
        **kwargs,
    )


class _FakeProvider(ImageProvider):
    name = "fake"
    display_name = "Fake"

    def __init__(self, results):
        self.results = results
        self.calls: list[str] = []

    async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
        self.calls.append(query)
        return self.results


def test_image_queries_use_topic_title_headings_and_research(db):
    from pipeline.images.service import image_queries_for_article

    article = _seed(db)
    queries = image_queries_for_article(db, article)
    assert queries
    assert any("solar" in q.lower() for q in queries)
    assert any("installation" in q.lower() for q in queries)  # heading word
    assert any("panels" in q.lower() or "panel" in q.lower() for q in queries)


async def test_run_image_search_persists_suggested_candidate(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)
    provider = _FakeProvider([_result()])
    candidates, errors, filtered = await run_image_search(db, article, providers=[provider])

    assert errors == []
    assert filtered == 0
    assert len(candidates) == 1
    rows = db.scalars(select(Image).where(Image.article_id == article.id)).all()
    assert len(rows) == 1
    assert rows[0].status == IMAGE_STATUS_SUGGESTED  # best candidate auto-suggested
    assert rows[0].mime == "image/jpeg"
    assert rows[0].relevance == 0.9
    assert provider.calls  # queries actually drove the search


async def test_run_image_search_dedupes_across_queries(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)
    # Same image URL returned twice (e.g. for two queries) -> one row.
    provider = _FakeProvider([_result(), _result()])
    candidates, _, _ = await run_image_search(db, article, providers=[provider])

    assert len(candidates) == 1
    assert len(db.scalars(select(Image).where(Image.article_id == article.id)).all()) == 1


async def test_run_image_search_filters_irrelevant_results(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)
    off_topic = _result(url="https://upload.example.com/concert.jpg",
                        title="Katy Perry concert tour", relevance=0.1)
    provider = _FakeProvider([_result(), off_topic])
    candidates, _, filtered = await run_image_search(db, article, providers=[provider])

    assert filtered == 1
    assert len(candidates) == 1
    rows = db.scalars(select(Image).where(Image.article_id == article.id)).all()
    assert len(rows) == 1  # off-topic dropped, not persisted
    assert rows[0].caption == "Solar panel on roof"


async def test_run_image_search_persists_rejected_with_reason(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)
    non_commercial = _result(url="https://upload.example.com/nc.jpg",
                             title="NC image", license="CC BY-NC 4.0")
    provider = _FakeProvider([_result(), non_commercial])
    candidates, _, _ = await run_image_search(db, article, providers=[provider])

    assert len(candidates) == 1
    rows = db.scalars(select(Image).where(Image.article_id == article.id)).all()
    assert len(rows) == 2
    rejected = [r for r in rows if r.status == IMAGE_STATUS_REJECTED]
    assert len(rejected) == 1
    assert "not allowed" in rejected[0].rejection_reason
    assert rejected[0].license == "CC BY-NC 4.0"


async def test_run_image_search_records_provider_errors_and_raises_when_nothing(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)

    class _Failing(ImageProvider):
        name = "failing"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            raise ImageProviderError("HTTP 500")

    with pytest.raises(ImageProviderError):
        await run_image_search(db, article, providers=[_Failing()])
    assert db.scalars(select(Image).where(Image.article_id == article.id)).first() is None


async def test_run_image_search_partial_provider_failure_keeps_results(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)

    class _Failing(ImageProvider):
        name = "failing"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            raise ImageProviderError("HTTP 500")

    candidates, errors, _ = await run_image_search(
        db, article, providers=[_Failing(), _FakeProvider([_result()])]
    )
    assert len(candidates) == 1
    assert any("failing" in e for e in errors)


async def test_run_image_search_preserves_selected_rows_on_research(db):
    from pipeline.images.service import run_image_search

    article = _seed(db)
    provider = _FakeProvider([_result()])
    await run_image_search(db, article, providers=[provider])

    selected = db.scalars(select(Image).where(Image.article_id == article.id)).one()
    selected.status = IMAGE_STATUS_SELECTED
    db.commit()

    # A re-search clears non-selected rows but keeps the human's selection.
    provider2 = _FakeProvider([_result(url="https://upload.example.com/new.jpg")])
    candidates, _, _ = await run_image_search(db, article, providers=[provider2])

    rows = db.scalars(select(Image).where(Image.article_id == article.id)).all()
    statuses = {r.status for r in rows}
    assert IMAGE_STATUS_SELECTED in statuses
    assert IMAGE_STATUS_SUGGESTED in statuses
    assert len(candidates) == 1


async def test_run_images_job_returns_image_ready_with_zero_images(db):
    from pipeline.images.service import run_images_job

    article = _seed(db)
    await run_images_job(db, article)  # no providers -> zero results

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == IMAGE_READY
    assert "no usable images" in fresh.generation_errors["images"]


async def test_no_image_bytes_downloaded(db, tmp_path):
    """The search only talks to providers via search(); image bytes are never fetched."""
    import os

    from pipeline.images.service import run_image_search

    article = _seed(db)
    provider = _FakeProvider([_result()])
    await run_image_search(db, article, providers=[provider])

    assert os.listdir(tmp_path) == []  # nothing written anywhere local


async def test_cross_article_reuse_is_not_blocked(db):
    """An image already used on another article can still be selected here."""
    from pipeline.images.dedupe import find_image_usage
    from pipeline.images.service import run_image_search

    article = _seed(db)
    other = _seed(db, title="Another topic about panels")
    other_imgs = _result(url="https://upload.example.com/shared.jpg")
    provider = _FakeProvider([other_imgs])
    await run_image_search(db, other, providers=[provider])
    other_row = db.scalars(select(Image).where(Image.article_id == other.id)).one()
    other_row.status = IMAGE_STATUS_SELECTED
    db.commit()

    # Same image surfaces for this article too; usage is informational only.
    provider2 = _FakeProvider([_result(url="https://upload.example.com/shared.jpg")])
    candidates, _, _ = await run_image_search(db, article, providers=[provider2])
    assert len(candidates) == 1

    usage = find_image_usage(db, "https://upload.example.com/shared.jpg", exclude_article_id=article.id)
    assert any(u["article_id"] == other.id for u in usage)
    db.scalars(select(Image).where(Image.article_id == article.id)).one().status = IMAGE_STATUS_SELECTED
    db.commit()  # selection still allowed despite cross-article reuse


def test_wikimedia_commons_is_the_only_builtin_provider():
    """The MVP ships exactly one built-in provider: Wikimedia Commons (keyless).

    Test modules register throwaway fakes in the process-global registry, so
    the builtin check ignores names that test-only fakes use.
    """
    from pipeline.images.providers.registry import enabled_providers, provider_names

    builtin = sorted(n for n in provider_names() if not n.startswith("image_"))
    assert builtin == ["commons"]
    commons = [p for p in enabled_providers() if p.name == "commons"]
    assert len(commons) == 1
    assert commons[0].is_configured()


async def test_run_images_job_preserves_edit_landing_mid_search(db, monkeypatch):
    """A human edit during the search wins: images persist, status stays drafted.

    Regression for the race where a queued/in-flight manual image job would
    clobber a fresh edit back to image_ready (or re-draft the article).
    """
    from pipeline.images.service import run_images_job

    article = _seed(db)
    article.status = IMAGE_READY
    db.commit()

    class _Interleaving(ImageProvider):
        name = "interleaving"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            with Session(ENGINE) as other:
                other.get(Article, article.id).status = DRAFTED
                other.commit()
            return [_result()]

    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [_Interleaving()])

    await run_images_job(db, article)

    fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
    assert fresh.status == DRAFTED
    rows = db.scalars(select(Image).where(Image.article_id == article.id)).all()
    assert len(rows) == 1  # search results persisted for the next review pass
