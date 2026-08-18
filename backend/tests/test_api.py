"""API smoke tests: health, ideas CRUD, settings allowlist + secrets masking.

Each test gets a fresh temp SQLite database via the DATABASE_URL env var,
set before `app.main` is imported.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_test_db = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db}"

from app.main import app  # noqa: E402  (needs DATABASE_URL set first)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_db():
    """Drop + recreate all tables between tests (the file DB is shared)."""
    from db.base import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def no_image_providers(monkeypatch):
    """Keep the article job's image stage network-free (no enabled providers)."""
    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [])


def test_health_ok(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert "ollama" in data


def test_idea_create_and_list(client):
    created = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    assert created["id"] == 1
    assert created["title"] == "Why solar panels work"

    listing = client.get("/api/ideas").json()
    assert len(listing) == 1
    assert listing[0]["id"] == created["id"]


def test_idea_not_found(client):
    assert client.get("/api/ideas/999").status_code == 404


def test_idea_validation(client):
    assert client.post("/api/ideas", json={"title": ""}).status_code == 422


def test_settings_write_allowlisted(client):
    updated = client.put("/api/settings/ollama_default_model", json={"value": "qwen2.5:7b"}).json()
    assert updated["value"] == "qwen2.5:7b"
    keys = [s["key"] for s in client.get("/api/settings").json()]
    assert "ollama_default_model" in keys


def test_settings_blocks_non_writable(client):
    assert client.put("/api/settings/encryption_key", json={"value": "x"}).status_code == 403


def test_settings_masks_secret_values(client):
    client.put("/api/settings/ollama_default_model", json={"value": "visible-value"})
    rows = client.get("/api/settings").json()
    for row in rows:
        if row["key"] in {"encryption_key", "local_auth_token"}:
            assert row["value"] == "********"


@pytest.fixture
def noop_runner(monkeypatch):
    """Replace the background runner's job with a recording no-op.

    Keeps API tests deterministic and network-free: a research run is queued
    but never actually executes providers/LLM in this process.
    """
    started: list[int] = []

    async def fake_run(research_id: int, limit: int) -> None:
        started.append(research_id)

    monkeypatch.setattr("services.research_runner._run", fake_run)
    return started


def test_start_research_queues_job(client, noop_runner):
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    start = client.post(f"/api/ideas/{idea['id']}/research").json()
    assert start["cached"] is False
    assert start["status"] == "researching"

    # The worker thread records the id asynchronously; poll briefly.
    import time

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and noop_runner != [start["id"]]:
        time.sleep(0.05)
    assert noop_runner == [start["id"]]

    research = client.get(f"/api/research/{start['id']}").json()
    assert research["id"] == start["id"]
    assert research["status"] == "researching"
    assert research["sources"] == []


def test_research_not_found(client):
    assert client.get("/api/research/999").status_code == 404


def test_research_list_and_dashboard_empty(client):
    assert client.get("/api/research").json() == []
    data = client.get("/api/dashboard").json()
    assert data["idea_count"] == 0
    assert data["research_count"] == 0
    assert data["article_count"] == 0
    assert data["publish_job_count"] == 0
    assert data["publish_success_count"] == 0
    assert data["publish_fail_count"] == 0
    assert data["scheduled_count"] == 0


def test_dashboard_counts(client):
    client.post("/api/ideas", json={"title": "A"})
    client.post("/api/ideas", json={"title": "B"})
    data = client.get("/api/dashboard").json()
    assert data["idea_count"] == 2


# --- article endpoints -----------------------------------------------------


@pytest.fixture
def noop_article_runner(monkeypatch):
    """Record article/recheck job ids synchronously without running the pipeline.

    Patches the call-site names in `app.api.articles` so `running` stays true
    for queued ids and the worker thread never runs real jobs (no races).
    """

    def _record(queued: list[int]) -> "object":
        return lambda article_id: queued.append(article_id)

    gen_started: list[int] = []
    recheck_started: list[int] = []
    monkeypatch.setattr("app.api.articles.start_background_article", _record(gen_started))
    monkeypatch.setattr("app.api.articles.start_background_recheck", _record(recheck_started))
    monkeypatch.setattr(
        "app.api.articles.is_running",
        lambda article_id: article_id in gen_started or article_id in recheck_started,
    )
    return gen_started, recheck_started


class _FakeSummaryClient:
    async def chat(self, messages, *, model=None, format=None, options=None, timeout=None):
        return "Summary text here.\n\nKEY POINTS:\n- p1\n- p2"


def _complete_research_for_idea(client, idea_id: int) -> dict:
    """Drive the research service to a completed state on the same engine."""
    import asyncio

    from db.base import engine
    from db.models import Idea, Research
    from pipeline.research import ResearchOutput
    from pipeline.research.providers.base import Source
    from pipeline.research.service import create_research, run_research_job
    from sqlalchemy.orm import Session

    async def fake_run_research(topic, limit=5, providers=None):
        return ResearchOutput(
            topic=topic,
            sources=[
                Source(provider="fake", title=f"{topic} A", url="https://example.com/a", snippet="snippet a"),
                Source(provider="fake", title=f"{topic} B", url="https://example.com/b", snippet="snippet b"),
            ],
            providers_attempted=["fake"],
        )

    import pipeline.research.service as research_service

    research_service.run_research = fake_run_research
    session = Session(engine)
    try:
        idea = session.get(Idea, idea_id)
        topic = idea.title if idea else f"topic-{idea_id}"
        research = create_research(session, idea_id, topic)
        asyncio.run(
            run_research_job(
                session, research, topic=topic, client=_FakeSummaryClient()
            )
        )
        fresh = session.get(Research, research.id)
        return {"id": fresh.id, "status": fresh.status, "summary": fresh.summary_text}
    finally:
        session.close()


def test_article_create_requires_research(client, noop_article_runner):
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    assert client.post(f"/api/articles?idea_id={idea['id']}").status_code == 409


def test_article_create_requires_complete_research(client, noop_article_runner, noop_runner):
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    client.post(f"/api/ideas/{idea['id']}/research")  # stays 'researching' (noop runner)
    assert client.post(f"/api/articles?idea_id={idea['id']}").status_code == 409


def test_article_create_and_generate_flow(client, noop_article_runner):
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    research = _complete_research_for_idea(client, idea["id"])
    assert research["status"] == "complete"
    assert "Summary text" in research["summary"]

    created = client.post(f"/api/articles?idea_id={idea['id']}")
    assert created.status_code == 201
    start = created.json()
    assert start["status"] == "draft"

    detail = client.get(f"/api/articles/{start['id']}").json()
    assert detail["id"] == start["id"]
    assert detail["title"] == "Why solar panels work"
    assert detail["slug"] == "why-solar-panels-work"
    assert detail["idea_title"] == "Why solar panels work"
    assert "Summary text" in detail["summary_text"]
    assert len(detail["sources"]) == 2
    assert detail["running"] is True  # job queued by the runner


def test_article_create_prevents_duplicate(client, noop_article_runner):
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    _complete_research_for_idea(client, idea["id"])
    assert client.post(f"/api/articles?idea_id={idea['id']}").status_code == 201
    assert client.post(f"/api/articles?idea_id={idea['id']}").status_code == 409


def test_article_list_empty_and_after_create(client, noop_article_runner):
    assert client.get("/api/articles").json() == []
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    _complete_research_for_idea(client, idea["id"])
    start = client.post(f"/api/articles?idea_id={idea['id']}").json()
    listing = client.get("/api/articles").json()
    assert len(listing) == 1
    assert listing[0]["id"] == start["id"]


def test_article_not_found(client):
    assert client.get("/api/articles/999").status_code == 404


def _make_image_ready_article(client, noop_article_runner=None):
    """Create an article and manually drive it to the image_ready state.

    Built via the service (not the create endpoint) so no background job is
    queued — the article is genuinely idle for the image endpoints.
    """
    idea = client.post("/api/ideas", json={"title": "Why solar panels work"}).json()
    _complete_research_for_idea(client, idea["id"])

    import asyncio

    from db.base import engine
    from db.models import Article, Research
    from pipeline.article.service import create_article_from_research, run_article_job
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    class FakeArticleClient:
        async def chat(self, messages, *, model=None, format=None, options=None, timeout=None):
            if format == "json":
                return (
                    '{"seo_title": "Solar panels explained", '
                    '"meta_description": "How PV cells work.", '
                    '"labels": ["solar", "pv"]}'
                )
            return (
                "TITLE: Why solar panels work\nBODY:\n"
                "## Introduction\n\nSolar panels convert sunlight into electricity. "
                "## Costs\n\nPrices have fallen over the past decade."
            )

    session = Session(engine)
    try:
        research = session.scalars(
            select(Research).where(Research.idea_id == idea["id"]).order_by(Research.id.desc()).limit(1)
        ).one()
        article = create_article_from_research(session, research)
        asyncio.run(run_article_job(session, article, client=FakeArticleClient()))
        return article.id
    finally:
        session.close()


def test_article_detail_shows_image_ready_state(client, noop_article_runner):
    article_id = _make_image_ready_article(client, noop_article_runner)
    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["status"] == "image_ready"
    assert detail["seo_title"] == "Solar panels explained"
    assert detail["word_count"] > 0
    check_types = {c["check_type"] for c in detail["check_results"]}
    assert check_types == {"seo", "quality", "policy", "repetition"}


def test_article_patch_content_edit_resets_and_clears_checks(client, noop_article_runner):
    article_id = _make_image_ready_article(client, noop_article_runner)
    patched = client.patch(f"/api/articles/{article_id}", json={"body": "## New\n\nFresh body text here."}).json()
    assert patched["status"] == "drafted"
    assert patched["check_results"] == []
    assert patched["word_count"] == 5


def test_article_patch_seo_edit_resets_and_clears_checks(client, noop_article_runner):
    """Editing SEO fields invalidates checks too (they depend on that metadata)."""
    article_id = _make_image_ready_article(client, noop_article_runner)
    patched = client.patch(
        f"/api/articles/{article_id}",
        json={"meta_description": "A brand new meta description."},
    ).json()
    assert patched["status"] == "drafted"
    assert patched["check_results"] == []
    assert patched["meta_description"] == "A brand new meta description."


def test_article_approve_flow(client, noop_article_runner):
    article_id = _make_image_ready_article(client, noop_article_runner)

    ready = client.post(f"/api/articles/{article_id}/approve").json()
    assert ready["status"] == "ready_for_review"
    assert ready["review_approved_at"] is None

    approved = client.post(f"/api/articles/{article_id}/approve").json()
    assert approved["status"] == "approved"
    assert approved["review_approved_at"] is not None


def test_article_approve_rejects_non_reviewable_state(client, noop_article_runner):
    article_id = _make_image_ready_article(client, noop_article_runner)
    # Reset to a state that cannot be approved.
    client.patch(f"/api/articles/{article_id}", json={"body": "## New\n\nFresh body."})
    resp = client.post(f"/api/articles/{article_id}/approve")
    assert resp.status_code == 409


def test_article_recheck_queues_and_retains_body(client, noop_article_runner):
    article_id = _make_image_ready_article(client, noop_article_runner)
    resp = client.post(f"/api/articles/{article_id}/recheck")
    assert resp.status_code == 200
    assert resp.json()["id"] == article_id
    assert noop_article_runner[1] == [article_id]


def test_article_retry_only_in_retryable_state(client, noop_article_runner):
    article_id = _make_image_ready_article(client, noop_article_runner)
    assert client.post(f"/api/articles/{article_id}/retry").status_code == 409
    # A fresh (draft) article IS retryable.
    idea = client.post("/api/ideas", json={"title": "Another topic"}).json()
    _complete_research_for_idea(client, idea["id"])
    start = client.post(f"/api/articles?idea_id={idea['id']}").json()
    retry = client.post(f"/api/articles/{start['id']}/retry")
    assert retry.status_code == 200
    assert start["id"] in noop_article_runner[0]


# --- Image API ---------------------------------------------------------------


def _seed_image_rows(article_id: int, **kwargs) -> dict:
    """Insert image rows directly for the article (bypasses the search job)."""
    from db.base import engine
    from db.models import Image
    from sqlalchemy.orm import Session

    base = dict(
        provider="commons",
        url="https://upload.wikimedia.org/wikipedia/commons/a.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:Test.jpg",
        caption="Test image",
        license="CC0",
        status="candidate",
        thumb_url="https://upload.wikimedia.org/wikipedia/commons/thumb/a.jpg",
        mime="image/jpeg",
        width=1200,
        height=800,
        file_size=2048,
        relevance=0.9,
        rejection_reason=None,
    )
    base.update(kwargs)
    session = Session(engine)
    try:
        row = Image(article_id=article_id, **base)
        session.add(row)
        session.commit()
        return {"id": row.id, **base}
    finally:
        session.close()


def test_images_list_empty(client):
    article_id = _make_image_ready_article(client)
    data = client.get(f"/api/articles/{article_id}/images").json()
    assert data["article_id"] == article_id
    assert data["status"] == "image_ready"
    assert data["running"] is False
    assert data["images"] == []


def test_images_search_queues_job(client, monkeypatch):
    article_id = _make_image_ready_article(client)
    started: list[int] = []
    monkeypatch.setattr("app.api.articles.start_background_images", started.append)

    resp = client.post(f"/api/articles/{article_id}/images/search")
    assert resp.status_code == 202
    data = resp.json()
    assert data["article_id"] == article_id
    assert started == [article_id]


def test_images_search_requires_searchable_state(client):
    # A fresh article (draft) cannot be searched.
    idea = client.post("/api/ideas", json={"title": "Draft topic"}).json()
    _complete_research_for_idea(client, idea["id"])
    start = client.post(f"/api/articles?idea_id={idea['id']}").json()
    resp = client.post(f"/api/articles/{start['id']}/images/search")
    assert resp.status_code == 409


def test_images_search_rejects_second_job(client, monkeypatch):
    article_id = _make_image_ready_article(client)
    monkeypatch.setattr("app.api.articles.start_background_images", lambda _id: None)
    monkeypatch.setattr("app.api.articles.is_running", lambda _id: True)  # job in flight

    resp = client.post(f"/api/articles/{article_id}/images/search")
    assert resp.status_code == 409


def test_images_retry_queues_job(client, monkeypatch):
    article_id = _make_image_ready_article(client)
    started: list[int] = []
    monkeypatch.setattr("app.api.articles.start_background_images", started.append)
    resp = client.post(f"/api/articles/{article_id}/images/retry")
    assert resp.status_code == 202
    assert started == [article_id]


def test_images_select_sets_selected_and_does_not_approve(client):
    article_id = _make_image_ready_article(client)
    row = _seed_image_rows(article_id)

    resp = client.post(f"/api/articles/{article_id}/images/{row['id']}/select")
    assert resp.status_code == 200
    images = resp.json()["images"]
    assert images[0]["status"] == "selected"

    # Selection is NOT approval: the article still needs the review gate.
    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["status"] == "image_ready"
    ready = client.post(f"/api/articles/{article_id}/approve").json()
    assert ready["status"] == "ready_for_review"
    approved = client.post(f"/api/articles/{article_id}/approve").json()
    assert approved["status"] == "approved"


def test_images_select_requires_article_ownership(client):
    article_a = _make_image_ready_article(client)
    idea = client.post("/api/ideas", json={"title": "Second article"}).json()
    _complete_research_for_idea(client, idea["id"])
    start_b = client.post(f"/api/articles?idea_id={idea['id']}").json()
    row = _seed_image_rows(article_a)

    # Selecting article A's image via article B's endpoint must fail.
    resp = client.post(f"/api/articles/{start_b['id']}/images/{row['id']}/select")
    assert resp.status_code == 404


def test_images_select_rejects_rejected_image(client):
    article_id = _make_image_ready_article(client)
    row = _seed_image_rows(article_id, status="rejected", rejection_reason="license not allowed: CC BY-NC 4.0")
    resp = client.post(f"/api/articles/{article_id}/images/{row['id']}/select")
    assert resp.status_code == 409
    assert "rejected" in resp.json()["detail"]


def test_images_remove_deletes_row(client):
    article_id = _make_image_ready_article(client)
    row = _seed_image_rows(article_id)
    resp = client.delete(f"/api/articles/{article_id}/images/{row['id']}")
    assert resp.status_code == 200
    assert resp.json()["images"] == []


def test_images_remove_requires_ownership(client):
    article_a = _make_image_ready_article(client)
    idea = client.post("/api/ideas", json={"title": "Second article"}).json()
    _complete_research_for_idea(client, idea["id"])
    start_b = client.post(f"/api/articles?idea_id={idea['id']}").json()
    row = _seed_image_rows(article_a)
    resp = client.delete(f"/api/articles/{start_b['id']}/images/{row['id']}")
    assert resp.status_code == 404


def test_images_queued_job_noops_after_edit(client, noop_article_runner):
    """A manual image job that starts late after an edit must not clobber it."""
    import asyncio

    from services.article_runner import _run_images

    article_id = _make_image_ready_article(client)
    client.patch(
        f"/api/articles/{article_id}", json={"body": "## New\n\nEdited while queued."}
    )
    assert client.get(f"/api/articles/{article_id}").json()["status"] == "drafted"

    # The queued manual job starts after the edit: it must be a no-op, not a
    # re-draft. (The mid-search interleaving is covered in test_images_service.)
    asyncio.run(_run_images(article_id))

    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["status"] == "drafted"
    assert detail["body"] == "## New\n\nEdited while queued."
    assert client.get(f"/api/articles/{article_id}/images").json()["images"] == []
