"""Blogger connection API tests.

Tests the 5 endpoints (status, connect, callback, blogs, disconnect)
with mocked BloggerClient. Callback is a public endpoint (no auth).
All other endpoints use the local auth token dependency.
"""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import os

_test_db = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db}"

from app.config import get_settings
get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app  # noqa: E402
from app.api.blogger import (
    _PENDING_STATES,
    _make_state,
    _register_state,
    _consume_state,
    _cleanup_expired_states,
    _STATE_TTL_SECONDS,
)


_TEST_ENCRYPTION_KEY = "QgfJenhfUGGdtE4D55hvDZ70h4LHbsjmebD10qBN0RQ="
_TEST_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
_TEST_CLIENT_SECRET = "test-client-secret"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _set_test_config(monkeypatch):
    """Set Blogger + encryption config via monkeypatch (cleaned up automatically)."""
    monkeypatch.setenv("ENCRYPTION_KEY", _TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("BLOGGER_CLIENT_ID", _TEST_CLIENT_ID)
    monkeypatch.setenv("BLOGGER_CLIENT_SECRET", _TEST_CLIENT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_db():
    from db.base import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def noop_image_providers(monkeypatch):
    monkeypatch.setattr("pipeline.images.service.enabled_providers", lambda: [])


@pytest.fixture(autouse=True)
def clear_pending_states():
    _PENDING_STATES.clear()
    yield
    _PENDING_STATES.clear()


# --- Helpers ----------------------------------------------------------------


def _make_valid_token_material():
    from services.blogger_client import TokenMaterial

    return TokenMaterial(
        access_token="ya29.access",
        refresh_token="1//refresh",
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _make_expired_token_material():
    from services.blogger_client import TokenMaterial

    return TokenMaterial(
        access_token="ya29.expired",
        refresh_token="1//refresh-expired",
        expiry=datetime.now(timezone.utc) - timedelta(hours=1),
    )


def _mock_blog(id="b1", name="My Blog", url="https://my.blogspot.com", description="A blog"):
    from services.blogger_client import BloggerBlog

    return BloggerBlog(id=id, name=name, url=url, description=description)


def _encrypt_token(token) -> str:
    from app.config import get_settings
    from services.blogger_client import TokenCryptor

    settings = get_settings()
    return TokenCryptor(settings.encryption_key).encrypt_token(token)


def _seed_connected_blog(token=None, blog_id="12345", status="connected"):
    """Insert a BlogConnection row with encrypted token directly."""
    from db.base import engine
    from db.models import BlogConnection
    from sqlalchemy.orm import Session

    if token is None:
        token = _make_valid_token_material()
    encrypted = _encrypt_token(token)

    session = Session(engine)
    try:
        conn = BlogConnection(
            name="Test Blog",
            blog_id=blog_id,
            blog_url="https://test.blogspot.com",
            token_encrypted=encrypted,
            status=status,
        )
        session.add(conn)
        session.commit()
        return conn
    finally:
        session.close()


# --- State management tests -------------------------------------------------


class TestStateManagement:
    def test_make_state_format(self):
        state = _make_state()
        parts = state.split(".")
        assert len(parts) == 2
        assert len(parts[0]) > 10
        assert len(parts[1]) == 32

    def test_register_and_consume(self):
        state = _make_state()
        _register_state(state)
        assert state in _PENDING_STATES
        assert _consume_state(state) is True
        assert state not in _PENDING_STATES

    def test_consume_invalid_state(self):
        assert _consume_state("invalid.state") is False

    def test_consume_expired_state(self):
        state = _make_state()
        _PENDING_STATES[state] = time.time() - _STATE_TTL_SECONDS - 1
        assert _consume_state(state) is False

    def test_cleanup_evicts_expired(self):
        old = _make_state()
        fresh = _make_state()
        _register_state(old)
        _register_state(fresh)
        _PENDING_STATES[old] = time.time() - _STATE_TTL_SECONDS - 1
        _cleanup_expired_states()
        assert old not in _PENDING_STATES
        assert fresh in _PENDING_STATES


# --- GET /api/blogger/status ------------------------------------------------


class TestBloggerStatus:
    def test_no_connection(self, client):
        resp = client.get("/api/blogger/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["status"] == "disconnected"

    def test_connected(self, client):
        _seed_connected_blog()
        resp = client.get("/api/blogger/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["status"] == "connected"
        assert data["blog_id"] == "12345"
        assert data["blog_url"] == "https://test.blogspot.com"
        assert data["blog_name"] == "Test Blog"

    def test_token_expired(self, client):
        token = _make_expired_token_material()
        _seed_connected_blog(token=token)
        resp = client.get("/api/blogger/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["status"] == "token_expired"

    def test_connected_with_decrypt_error(self, client):
        """Corrupt the encrypted token — should return disconnected."""
        from db.base import engine
        from db.models import BlogConnection
        from sqlalchemy.orm import Session

        session = Session(engine)
        try:
            conn = BlogConnection(
                name="Corrupt Blog",
                token_encrypted="not-valid-fernet",
                status="connected",
            )
            session.add(conn)
            session.commit()
        finally:
            session.close()

        resp = client.get("/api/blogger/status")
        assert resp.status_code == 200
        assert resp.json()["connected"] is False


# --- POST /api/blogger/connect ----------------------------------------------


class TestBloggerConnect:
    def test_returns_auth_url(self, client):
        resp = client.post("/api/blogger/connect")
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_url" in data
        assert "accounts.google.com" in data["auth_url"]
        assert "blogger" in data["auth_url"]

    def test_creates_pending_state(self, client):
        assert len(_PENDING_STATES) == 0
        resp = client.post("/api/blogger/connect")
        assert len(_PENDING_STATES) == 1
        auth_url = resp.json()["auth_url"]
        # State is embedded in the URL
        import urllib.parse
        parsed = urllib.parse.urlparse(auth_url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]
        assert state in _PENDING_STATES

    def test_connect_when_already_connected(self, client):
        """Connect works even when already connected — allows re-auth."""
        _seed_connected_blog()
        resp = client.post("/api/blogger/connect")
        assert resp.status_code == 200
        assert "auth_url" in resp.json()


# --- GET /api/blogger/callback ----------------------------------------------


class TestBloggerCallback:
    def test_callback_success(self, client):
        """Valid code + state → tokens stored, blog fetched."""
        state = _make_state()
        _register_state(state)

        mock_token = _make_valid_token_material()
        mock_blog = _mock_blog(id="blog-1", name="My Blog", url="https://blog1.blogspot.com", description="desc")

        with (
            patch("app.api.blogger.BloggerClient") as MockClient,
        ):
            instance = MockClient.return_value
            instance.exchange_code = AsyncMock(return_value=mock_token)
            instance.list_blogs = AsyncMock(return_value=[mock_blog])

            resp = client.get(
                f"/api/blogger/callback?code=auth_code_123&state={state}"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connected"
        assert data["blog_id"] == "blog-1"

    def test_callback_creates_connection_row(self, client):
        state = _make_state()
        _register_state(state)
        mock_token = _make_valid_token_material()
        mock_blog = _mock_blog(id="b1", name="Blog", url="https://b1.blogspot.com", description="")

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(return_value=mock_token)
            inst.list_blogs = AsyncMock(return_value=[mock_blog])
            client.get(f"/api/blogger/callback?code=code&state={state}")

        from db.base import engine
        from db.models import BlogConnection
        from sqlalchemy.orm import Session

        session = Session(engine)
        try:
            conn = session.scalars(select(BlogConnection)).first()
            assert conn is not None
            assert conn.status == "connected"
            assert conn.token_encrypted is not None
            assert conn.blog_id == "b1"
        finally:
            session.close()

    def test_callback_empty_blog_list(self, client):
        """Exchange succeeds but no blogs — still connected, blog_id may be empty."""
        from sqlalchemy import select as sa_select

        state = _make_state()
        _register_state(state)
        mock_token = _make_valid_token_material()

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(return_value=mock_token)
            inst.list_blogs = AsyncMock(return_value=[])
            resp = client.get(f"/api/blogger/callback?code=c&state={state}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"

    def test_callback_denied(self, client):
        resp = client.get("/api/blogger/callback?error=access_denied")
        assert resp.status_code == 400
        assert "denied" in resp.json()["detail"].lower()

    def test_callback_denied_creates_disconnected_row(self, client):
        client.get("/api/blogger/callback?error=user_declined")
        from db.base import engine
        from db.models import BlogConnection
        from sqlalchemy.orm import Session

        session = Session(engine)
        try:
            conn = session.scalars(select(BlogConnection)).first()
            assert conn is not None
            assert conn.status == "disconnected"
        finally:
            session.close()

    def test_callback_invalid_state(self, client):
        resp = client.get("/api/blogger/callback?code=abc&state=invalid.x")
        assert resp.status_code == 400
        assert "Invalid or expired OAuth state" in resp.json()["detail"]

    def test_callback_missing_state(self, client):
        resp = client.get("/api/blogger/callback?code=abc")
        assert resp.status_code == 400

    def test_callback_no_code(self, client):
        state = _make_state()
        _register_state(state)
        resp = client.get(f"/api/blogger/callback?state={state}")
        assert resp.status_code == 400
        assert "No authorization code" in resp.json()["detail"]

    def test_callback_exchange_fails(self, client):
        state = _make_state()
        _register_state(state)

        from services.blogger_client import BloggerAuthError

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(side_effect=BloggerAuthError("bad code"))
            resp = client.get(f"/api/blogger/callback?code=bad&state={state}")

        assert resp.status_code == 400
        assert "bad code" in resp.json()["detail"]

    def test_callback_exchange_timeout(self, client):
        state = _make_state()
        _register_state(state)

        from services.blogger_client import BloggerTimeoutError

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(side_effect=BloggerTimeoutError("timeout"))
            resp = client.get(f"/api/blogger/callback?code=c&state={state}")

        assert resp.status_code == 504

    def test_callback_exchange_generic_error(self, client):
        state = _make_state()
        _register_state(state)

        from services.blogger_client import BloggerError

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(side_effect=BloggerError("net err"))
            resp = client.get(f"/api/blogger/callback?code=c&state={state}")

        assert resp.status_code == 502

    def test_callback_blog_fetch_fails_gracefully(self, client):
        """Token exchange succeeds but list_blogs fails — still connected."""
        state = _make_state()
        _register_state(state)
        mock_token = _make_valid_token_material()

        from services.blogger_client import BloggerAPIError

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(return_value=mock_token)
            inst.list_blogs = AsyncMock(side_effect=BloggerAPIError("oops"))
            resp = client.get(f"/api/blogger/callback?code=c&state={state}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"

    def test_callback_state_consumed_cannot_reuse(self, client):
        """A valid state can only be used once."""
        state = _make_state()
        _register_state(state)
        mock_token = _make_valid_token_material()
        mock_blog = _mock_blog(id="b1", name="Blog", url="https://b1.blogspot.com", description="")

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(return_value=mock_token)
            inst.list_blogs = AsyncMock(return_value=[mock_blog])
            client.get(f"/api/blogger/callback?code=c1&state={state}")

        # Second use of same state should fail
        resp = client.get(f"/api/blogger/callback?code=c2&state={state}")
        assert resp.status_code == 400


# --- GET /api/blogger/blogs -------------------------------------------------


class TestBloggerBlogs:
    def test_not_connected(self, client):
        resp = client.get("/api/blogger/blogs")
        assert resp.status_code == 400
        assert "No Blogger account connected" in resp.json()["detail"]

    def test_list_blogs(self, client):
        _seed_connected_blog()
        mock_blog = _mock_blog(id="b1", name="My Blog", url="https://my.blogspot.com", description="A blog")

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.list_blogs = AsyncMock(return_value=[mock_blog])
            resp = client.get("/api/blogger/blogs")

        assert resp.status_code == 200
        blogs = resp.json()
        assert len(blogs) == 1
        assert blogs[0]["id"] == "b1"
        assert blogs[0]["name"] == "My Blog"

    def test_auth_error_disconnects(self, client):
        _seed_connected_blog()
        from services.blogger_client import BloggerAuthError

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.list_blogs = AsyncMock(side_effect=BloggerAuthError("token revoked"))
            resp = client.get("/api/blogger/blogs")

        assert resp.status_code == 401
        # Should also have disconnected
        status = client.get("/api/blogger/status").json()
        assert status["connected"] is False

    def test_api_error_returns_502(self, client):
        _seed_connected_blog()
        from services.blogger_client import BloggerAPIError

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.list_blogs = AsyncMock(side_effect=BloggerAPIError("500 internal"))
            resp = client.get("/api/blogger/blogs")

        assert resp.status_code == 502

    def test_token_decryption_error(self, client):
        """Token that fails decryption → 500."""
        from db.base import engine
        from db.models import BlogConnection
        from sqlalchemy.orm import Session

        session = Session(engine)
        try:
            conn = BlogConnection(
                name="Bad Token",
                token_encrypted="garbage",
                status="connected",
            )
            session.add(conn)
            session.commit()
        finally:
            session.close()

        resp = client.get("/api/blogger/blogs")
        assert resp.status_code == 500


# --- POST /api/blogger/disconnect -------------------------------------------


class TestBloggerDisconnect:
    def test_not_connected(self, client):
        resp = client.post("/api/blogger/disconnect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["status"] == "disconnected"

    def test_disconnect_clears_fields(self, client):
        _seed_connected_blog()
        resp = client.post("/api/blogger/disconnect")
        assert resp.status_code == 200
        assert resp.json()["connected"] is False

        # Verify DB state
        from db.base import engine
        from db.models import BlogConnection
        from sqlalchemy.orm import Session

        session = Session(engine)
        try:
            conn = session.scalars(select(BlogConnection)).first()
            assert conn is not None
            assert conn.token_encrypted is None
            assert conn.blog_id is None
            assert conn.blog_url is None
            assert conn.status == "disconnected"
        finally:
            session.close()

    def test_disconnect_then_status(self, client):
        _seed_connected_blog()
        client.post("/api/blogger/disconnect")
        status = client.get("/api/blogger/status").json()
        assert status["connected"] is False
        assert status["status"] == "disconnected"

    def test_disconnect_is_idempotent(self, client):
        resp1 = client.post("/api/blogger/disconnect")
        resp2 = client.post("/api/blogger/disconnect")
        assert resp1.json() == resp2.json()


# --- Full flow integration tests --------------------------------------------


class TestFullFlow:
    def test_full_connect_cycle(self, client):
        """status (disconnected) → connect → callback → status (connected) → blogs → disconnect → status (disconnected)."""
        # 1. Initial status
        status = client.get("/api/blogger/status").json()
        assert status["connected"] is False

        # 2. Connect
        connect_resp = client.post("/api/blogger/connect").json()
        assert "auth_url" in connect_resp

        # 3. Callback
        import urllib.parse
        parsed = urllib.parse.urlparse(connect_resp["auth_url"])
        state = urllib.parse.parse_qs(parsed.query)["state"][0]
        mock_token = _make_valid_token_material()
        mock_blog = _mock_blog(id="b1", name="My Blog", url="https://my.blogspot.com", description="")

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(return_value=mock_token)
            inst.list_blogs = AsyncMock(return_value=[mock_blog])
            cb_resp = client.get(f"/api/blogger/callback?code=code123&state={state}")
        assert cb_resp.json()["status"] == "connected"

        # 4. Status → connected
        status = client.get("/api/blogger/status").json()
        assert status["connected"] is True
        assert status["blog_id"] == "b1"

        # 5. Blogs
        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.list_blogs = AsyncMock(return_value=[mock_blog])
            blogs = client.get("/api/blogger/blogs").json()
        assert len(blogs) == 1

        # 6. Disconnect
        disc = client.post("/api/blogger/disconnect").json()
        assert disc["connected"] is False

        # 7. Status → disconnected
        status = client.get("/api/blogger/status").json()
        assert status["connected"] is False

    def test_reconnect_after_disconnect(self, client):
        """Disconnect then reconnect should work cleanly."""
        _seed_connected_blog()
        client.post("/api/blogger/disconnect")
        assert client.get("/api/blogger/status").json()["connected"] is False

        connect_resp = client.post("/api/blogger/connect").json()
        import urllib.parse
        parsed = urllib.parse.urlparse(connect_resp["auth_url"])
        state = urllib.parse.parse_qs(parsed.query)["state"][0]

        mock_token = _make_valid_token_material()
        mock_blog = _mock_blog(id="b2", name="New Blog", url="https://new.blogspot.com", description="")

        with patch("app.api.blogger.BloggerClient") as MockClient:
            inst = MockClient.return_value
            inst.exchange_code = AsyncMock(return_value=mock_token)
            inst.list_blogs = AsyncMock(return_value=[mock_blog])
            client.get(f"/api/blogger/callback?code=new_code&state={state}")

        status = client.get("/api/blogger/status").json()
        assert status["connected"] is True
        assert status["blog_id"] == "b2"
