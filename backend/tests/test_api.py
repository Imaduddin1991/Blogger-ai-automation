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
    assert client.get("/api/dashboard").json() == {
        "idea_count": 0,
        "research_count": 0,
        "article_count": 0,
        "publish_job_count": 0,
    }


def test_dashboard_counts(client):
    client.post("/api/ideas", json={"title": "A"})
    client.post("/api/ideas", json={"title": "B"})
    data = client.get("/api/dashboard").json()
    assert data["idea_count"] == 2
