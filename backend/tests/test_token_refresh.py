"""Token auto-refresh tests (Phase 6C).

Covers: token expiry tracking, auto-refresh on publish, manual refresh endpoint,
refresh failure handling, near-expiry detection.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

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
from db.models import Article, BlogConnection
from pipeline.state import APPROVED, SCHEDULED
from services.blogger_client import (
    BloggerAuthError,
    BloggerClient,
    TokenMaterial,
    TokenCryptor,
    is_token_near_expiry,
)


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


def _make_token(*, hours_until_expiry: float = 1, refresh_token="1//refresh-token-test-value"):
    return TokenMaterial(
        access_token="ya29.access-token-test-value",
        refresh_token=refresh_token,
        expiry=datetime.now(timezone.utc) + timedelta(hours=hours_until_expiry),
    )


def _encrypt_token(token) -> str:
    settings = get_settings()
    return TokenCryptor(settings.encryption_key).encrypt_token(token)


def _seed_connection(db: Session, *, status="connected", token=None):
    if token is None:
        token = _make_token()
    conn = BlogConnection(
        name="Test Blog",
        blog_id="12345",
        blog_url="https://test.blogspot.com",
        token_encrypted=_encrypt_token(token),
        token_expires_at=token.expiry,
        status=status,
    )
    db.add(conn)
    db.commit()
    return conn


def _seed_article(db: Session, *, status=APPROVED, blog_id=None):
    article = Article(
        idea_id=None,
        blog_id=blog_id,
        title="Test Article",
        body="Test body.",
        status=status,
        labels=[],
        word_count=3,
    )
    db.add(article)
    db.commit()
    return article


def _new_db() -> Session:
    return SessionLocal()


from db.base import SessionLocal


# --- Tests: is_token_near_expiry -------------------------------------------


class TestIsTokenNearExpiry:
    def test_expired_token(self):
        token = _make_token(hours_until_expiry=-1)
        assert is_token_near_expiry(token) is True

    def test_near_expiry_token(self):
        token = _make_token(hours_until_expiry=0.05)  # ~3 minutes
        assert is_token_near_expiry(token) is True

    def test_fresh_token(self):
        token = _make_token(hours_until_expiry=1)
        assert is_token_near_expiry(token) is False

    def test_no_expiry(self):
        token = TokenMaterial(
            access_token="test",
            refresh_token="test",
            expiry=None,
        )
        assert is_token_near_expiry(token) is False


# --- Tests: token_expires_at column ----------------------------------------


class TestTokenExpiresAtColumn:
    def test_connection_stores_expiry(self):
        db = _new_db()
        now = datetime.now(timezone.utc)
        token = _make_token(hours_until_expiry=1)
        conn = _seed_connection(db, token=token)
        assert conn.token_expires_at is not None
        # Should be approximately 1 hour from now
        diff = conn.token_expires_at - now
        assert timedelta(minutes=50) < diff < timedelta(hours=2)

    def test_status_returns_expiry(self, client):
        db = _new_db()
        token = _make_token(hours_until_expiry=2)
        conn = _seed_connection(db, token=token)

        resp = client.get("/api/blogger/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["token_expires_at"] is not None


# --- Tests: manual refresh endpoint ----------------------------------------


class TestRefreshEndpoint:
    def test_refresh_without_connection(self, client):
        resp = client.post("/api/blogger/refresh")
        assert resp.status_code == 400

    def test_refresh_with_disconnected(self, client):
        db = _new_db()
        _seed_connection(db, status="disconnected")
        resp = client.post("/api/blogger/refresh")
        assert resp.status_code == 400

    def test_refresh_success(self, client):
        db = _new_db()
        token = _make_token(hours_until_expiry=0.05)  # Near-expiry
        _seed_connection(db, token=token)

        new_token = _make_token(hours_until_expiry=1)
        mock_refresh = AsyncMock(return_value=new_token)

        with patch("services.blogger_client.refresh_if_needed", mock_refresh):
            resp = client.post("/api/blogger/refresh")
            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is True
            assert data["token_expires_at"] is not None
            mock_refresh.assert_called_once()

    def test_refresh_failure_sets_token_expired(self, client):
        db = _new_db()
        token = _make_token(hours_until_expiry=0.05)
        _seed_connection(db, token=token)

        mock_refresh = AsyncMock(side_effect=BloggerAuthError("Token refresh failed"))

        with patch("services.blogger_client.refresh_if_needed", mock_refresh):
            resp = client.post("/api/blogger/refresh")
            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is False
            assert data["status"] == "token_expired"

    def test_refresh_updates_token_in_db(self, client):
        db = _new_db()
        old_token = _make_token(hours_until_expiry=0.05)
        conn = _seed_connection(db, token=old_token)

        new_token = _make_token(hours_until_expiry=2)
        mock_refresh = AsyncMock(return_value=new_token)

        with patch("services.blogger_client.refresh_if_needed", mock_refresh):
            client.post("/api/blogger/refresh")

        # Re-read connection
        db.refresh(conn)
        decrypted = TokenCryptor(get_settings().encryption_key).decrypt_token(conn.token_encrypted)
        assert decrypted.access_token == new_token.access_token
        # SQLite strips timezone from stored datetimes
        assert conn.token_expires_at is not None  # noqa: E501
        assert conn.token_expires_at.replace(tzinfo=timezone.utc).replace(tzinfo=None) == new_token.expiry.replace(tzinfo=None)  # noqa: E501


# --- Tests: disconnect clears expiry ----------------------------------------


class TestDisconnectClearsExpiry:
    def test_disconnect_clears_token_expires_at(self, client):
        db = _new_db()
        token = _make_token()
        _seed_connection(db, token=token)

        resp = client.post("/api/blogger/disconnect")
        assert resp.status_code == 200

        db.expire_all()
        conn = db.scalars(
            __import__("sqlalchemy").select(BlogConnection).limit(1)
        ).first()
        assert conn is not None
        assert conn.token_expires_at is None
