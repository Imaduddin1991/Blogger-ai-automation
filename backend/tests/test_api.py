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
