"""Delete published post tests (Phase 6D).

Covers: delete endpoint (happy path, wrong state, missing post ID),
state transition PUBLISHED → DRAFT, publish log entry.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import os

_test_db = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db}"

from app.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app  # noqa: E402
from db.base import Base, apply_publish_column_migrations, engine
from db.models import Article, BlogConnection, PublishLog
from pipeline.state import APPROVED, DRAFT, PUBLISHED
from services.blogger_client import TokenMaterial, TokenCryptor


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _set_test_config(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "QgfJenhfUGGdtE4D55hvDZ70h4LHbsjmebD10qBN0RQ=")
    monkeypatch.delenv("LOCAL_AUTH_TOKEN", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    apply_publish_column_migrations(engine)
    yield


def _make_token():
    return TokenMaterial(
        access_token="ya29.access-token-test-value",
        refresh_token="1//refresh-token-test-value",
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _encrypt_token(token) -> str:
    settings = get_settings()
    return TokenCryptor(settings.encryption_key).encrypt_token(token)


def _seed_connection(db: Session):
    conn = BlogConnection(
        name="Test Blog",
        blog_id="12345",
        blog_url="https://test.blogspot.com",
        token_encrypted=_encrypt_token(_make_token()),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="connected",
    )
    db.add(conn)
    db.commit()
    return conn


def _seed_article(db: Session, *, status=PUBLISHED, blog_id=None, post_id="post-123"):
    article = Article(
        idea_id=None,
        blog_id=blog_id,
        title="Test Article",
        body="Test body.",
        status=status,
        labels=[],
        word_count=3,
        blogger_post_id=post_id,
        blogger_post_url="https://test.blogspot.com/post-123",
    )
    db.add(article)
    db.commit()
    return article


def _new_db() -> Session:
    return SessionLocal()


from db.base import SessionLocal


# --- Tests -------------------------------------------------------------------


class TestDeletePublishedPost:
    def test_delete_happy_path(self, client):
        db = _new_db()
        conn = _seed_connection(db)
        article = _seed_article(db, blog_id=conn.id)

        mock_delete = AsyncMock()
        with patch("services.blogger_client.BloggerClient.delete_post", mock_delete):
            resp = client.delete(f"/api/articles/{article.id}/publish")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["status"] == DRAFT
        mock_delete.assert_called_once_with(conn.blog_id, "post-123")

    def test_delete_transitions_to_draft(self, client):
        db = _new_db()
        conn = _seed_connection(db)
        article = _seed_article(db, blog_id=conn.id)

        with patch("services.blogger_client.BloggerClient.delete_post", AsyncMock()):
            client.delete(f"/api/articles/{article.id}/publish")

        db.refresh(article)
        assert article.status == DRAFT
        assert article.blogger_post_id is None
        assert article.blogger_post_url is None
        assert article.blogger_published_at is None

    def test_delete_logs_to_publish_log(self, client):
        db = _new_db()
        conn = _seed_connection(db)
        article = _seed_article(db, blog_id=conn.id)

        with patch("services.blogger_client.BloggerClient.delete_post", AsyncMock()):
            client.delete(f"/api/articles/{article.id}/publish")

        logs = list(db.scalars(
            __import__("sqlalchemy").select(PublishLog).where(PublishLog.article_id == article.id)
        ).all())
        assert len(logs) == 1
        assert logs[0].action == "delete"
        assert logs[0].result == "success"

    def test_delete_rejects_non_published(self, client):
        db = _new_db()
        conn = _seed_connection(db)
        article = _seed_article(db, status=APPROVED, blog_id=conn.id)

        resp = client.delete(f"/api/articles/{article.id}/publish")
        assert resp.status_code == 409

    def test_delete_rejects_no_post_id(self, client):
        db = _new_db()
        conn = _seed_connection(db)
        article = _seed_article(db, blog_id=conn.id, post_id=None)

        resp = client.delete(f"/api/articles/{article.id}/publish")
        assert resp.status_code == 400

    def test_delete_article_not_found(self, client):
        resp = client.delete("/api/articles/99999/publish")
        assert resp.status_code == 404

    def test_delete_api_error_keeps_published(self, client):
        from services.blogger_client import BloggerAPIError

        db = _new_db()
        conn = _seed_connection(db)
        article = _seed_article(db, blog_id=conn.id)

        mock_delete = AsyncMock(side_effect=BloggerAPIError("Not found: blogs/12345/posts/post-123"))
        with patch("services.blogger_client.BloggerClient.delete_post", mock_delete):
            resp = client.delete(f"/api/articles/{article.id}/publish")
            assert resp.status_code == 502

        db.refresh(article)
        assert article.status == PUBLISHED  # Should remain PUBLISHED on failure
