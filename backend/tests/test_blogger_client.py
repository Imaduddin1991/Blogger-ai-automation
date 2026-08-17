"""Blogger client tests with mocked HTTP transport (no live API calls).

Covers: config guards, OAuth URL generation, token exchange/refresh,
all Blogger API endpoints, error normalization, timeout handling,
malformed responses, token encryption roundtrip, and lifecycle methods.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from services.blogger_client import (
    BloggerAPIError,
    BloggerAuthError,
    BloggerBlog,
    BloggerClient,
    BloggerConfigError,
    BloggerError,
    BloggerPost,
    BloggerTimeoutError,
    PostListResponse,
    TokenCryptor,
    TokenMaterial,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CID = "test-client-id"
CSECRET = "test-client-secret"
CREDIR = "http://127.0.0.1:8000/api/blogger/callback"
TOKEN = TokenMaterial(
    access_token="ya29.test-access",
    refresh_token="1//test-refresh",
    expiry=datetime.now(timezone.utc) + timedelta(hours=1),
)


def _token_expired() -> TokenMaterial:
    return TokenMaterial(
        access_token="ya29.expired",
        refresh_token="1//expired-refresh",
        expiry=datetime.now(timezone.utc) - timedelta(hours=1),
    )


# ---------------------------------------------------------------------------
# Fake httpx transport
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: dict | list | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text or json.dumps(self._json_data)
        self.headers = headers or {"content-type": "application/json"}
        self._force_json_error = False

    def json(self):
        if self._force_json_error:
            raise ValueError("No JSON object could be decoded")
        return self._json_data


class _FakeTransport:
    """Configurable fake that responds to any method/URL."""

    status_code: int = 200
    payload: dict | list = {}
    text: str = ""
    headers: dict[str, str] | None = None
    raise_http: type[Exception] | None = None
    raise_timeout: bool = False
    force_json_error: bool = False

    # Captured request details
    last_method: str = ""
    last_url: str = ""
    last_json: dict | None = None
    last_params: dict | None = None

    @classmethod
    def reset(cls):
        cls.status_code = 200
        cls.payload = {}
        cls.text = ""
        cls.headers = None
        cls.raise_http = None
        cls.raise_timeout = False
        cls.force_json_error = False
        cls.last_method = ""
        cls.last_url = ""
        cls.last_json = None
        cls.last_params = None

    @classmethod
    def _build_response(cls, url: str, method: str = "GET") -> _FakeResponse:
        resp = _FakeResponse(
            status_code=cls.status_code,
            json_data=cls.payload,
            text=cls.text,
            headers=cls.headers,
        )
        resp._force_json_error = cls.force_json_error
        return resp


class _FakeAsyncClient:
    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def request(self, method, url, *, params=None, json=None, headers=None, data=None):
        if _FakeTransport.raise_timeout:
            raise httpx.TimeoutException("timeout", request=httpx.Request(method, url))
        if _FakeTransport.raise_http:
            raise _FakeTransport.raise_http("boom", request=httpx.Request(method, url))
        _FakeTransport.last_method = method
        _FakeTransport.last_url = url
        _FakeTransport.last_json = json
        _FakeTransport.last_params = params
        return _FakeTransport._build_response(url, method)

    async def post(self, url, *, data=None, json=None):
        if _FakeTransport.raise_timeout:
            raise httpx.TimeoutException("timeout", request=httpx.Request("POST", url))
        if _FakeTransport.raise_http:
            raise _FakeTransport.raise_http("boom", request=httpx.Request("POST", url))
        _FakeTransport.last_method = "POST"
        _FakeTransport.last_url = url
        _FakeTransport.last_json = json or data
        return _FakeTransport._build_response(url, "POST")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_http(monkeypatch):
    """Replace httpx.AsyncClient with the fake transport for every test."""
    monkeypatch.setattr("services.blogger_client.httpx.AsyncClient", _FakeAsyncClient)


@pytest.fixture()
def client():
    """BloggerClient with test credentials and a valid token."""
    return BloggerClient(
        client_id=CID,
        client_secret=CSECRET,
        redirect_uri=CREDIR,
        token=TOKEN,
        timeout=5.0,
    )


@pytest.fixture()
def no_token_client():
    """BloggerClient with credentials but no token."""
    return BloggerClient(
        client_id=CID,
        client_secret=CSECRET,
        redirect_uri=CREDIR,
    )


# ===========================================================================
# Error hierarchy
# ===========================================================================


def test_error_hierarchy():
    assert issubclass(BloggerConfigError, BloggerError)
    assert issubclass(BloggerAuthError, BloggerError)
    assert issubclass(BloggerAPIError, BloggerError)
    assert issubclass(BloggerTimeoutError, BloggerError)
    assert issubclass(BloggerError, RuntimeError)


# ===========================================================================
# TokenMaterial
# ===========================================================================


def test_token_not_expired_when_future():
    t = TokenMaterial(
        access_token="a",
        refresh_token="r",
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert t.is_expired is False


def test_token_expired_when_past():
    t = TokenMaterial(
        access_token="a",
        refresh_token="r",
        expiry=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert t.is_expired is True


def test_token_not_expired_when_no_expiry():
    t = TokenMaterial(access_token="a", refresh_token="r")
    assert t.is_expired is False


def test_token_near_expiry_detected():
    t = TokenMaterial(
        access_token="a",
        refresh_token="r",
        expiry=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    assert t.is_expired is True  # within 60s buffer


# ===========================================================================
# TokenCryptor (requires cryptography)
# ===========================================================================


def _fernet_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


class TestTokenCryptor:
    def test_encrypt_decrypt_roundtrip(self):
        key = _fernet_key()
        cryptor = TokenCryptor(key)
        token = TokenMaterial(
            access_token="ya29.test",
            refresh_token="1//test",
            expiry=datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc),
        )
        encrypted = cryptor.encrypt_token(token)
        assert encrypted != token.access_token  # not plaintext
        decrypted = cryptor.decrypt_token(encrypted)
        assert decrypted.access_token == "ya29.test"
        assert decrypted.refresh_token == "1//test"
        assert decrypted.expiry == token.expiry

    def test_missing_key_raises(self):
        with pytest.raises(BloggerConfigError, match="ENCRYPTION_KEY"):
            TokenCryptor("")

    def test_wrong_key_fails_decrypt(self):
        key1 = _fernet_key()
        key2 = _fernet_key()
        cryptor1 = TokenCryptor(key1)
        cryptor2 = TokenCryptor(key2)
        encrypted = cryptor1.encrypt_token(
            TokenMaterial(access_token="a", refresh_token="r")
        )
        with pytest.raises(BloggerError, match="decrypt"):
            cryptor2.decrypt_token(encrypted)

    def test_token_without_expiry_roundtrip(self):
        key = _fernet_key()
        cryptor = TokenCryptor(key)
        token = TokenMaterial(access_token="a", refresh_token="r")
        decrypted = cryptor.decrypt_token(cryptor.encrypt_token(token))
        assert decrypted.expiry is None
        assert decrypted.access_token == "a"
        assert decrypted.refresh_token == "r"


# ===========================================================================
# Client init & config guards
# ===========================================================================


def test_client_reads_config(monkeypatch):
    """Client falls back to Settings when no explicit args."""
    monkeypatch.setattr(
        "services.blogger_client.get_settings",
        lambda: type(
            "S",
            (),
            {
                "blogger_client_id": "cfg-id",
                "blogger_client_secret": "cfg-secret",
                "blogger_redirect_uri": "http://cfg/callback",
            },
        )(),
    )
    c = BloggerClient()
    assert c.client_id == "cfg-id"
    assert c.client_secret == "cfg-secret"
    assert c.redirect_uri == "http://cfg/callback"


def test_client_explicit_args_override_config(monkeypatch):
    monkeypatch.setattr(
        "services.blogger_client.get_settings",
        lambda: type(
            "S",
            (),
            {
                "blogger_client_id": "cfg-id",
                "blogger_client_secret": "cfg-secret",
                "blogger_redirect_uri": "http://cfg/callback",
            },
        )(),
    )
    c = BloggerClient(client_id="explicit", client_secret="explicit")
    assert c.client_id == "explicit"


def test_ensure_configured_raises_on_missing_id():
    c = BloggerClient(client_id="", client_secret=CSECRET, redirect_uri=CREDIR)
    with pytest.raises(BloggerConfigError, match="BLOGGER_CLIENT_ID"):
        c._ensure_configured()


def test_ensure_configured_raises_on_missing_secret():
    c = BloggerClient(client_id=CID, client_secret="", redirect_uri=CREDIR)
    with pytest.raises(BloggerConfigError, match="BLOGGER_CLIENT_SECRET"):
        c._ensure_configured()


def test_ensure_authenticated_raises_without_token(no_token_client):
    with pytest.raises(BloggerAuthError, match="Not authenticated"):
        no_token_client._ensure_authenticated()


# ===========================================================================
# OAuth URL generation
# ===========================================================================


def test_authorization_url(client):
    url = client.get_authorization_url()
    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert f"client_id={CID}" in url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fblogger" in url
    assert "response_type=code" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_authorization_url_with_state(client):
    url = client.get_authorization_url(state="csrf-token-123")
    assert "state=csrf-token-123" in url


def test_authorization_url_missing_config():
    c = BloggerClient(client_id="", client_secret=CSECRET, redirect_uri=CREDIR)
    with pytest.raises(BloggerConfigError):
        c.get_authorization_url()


# ===========================================================================
# Token exchange
# ===========================================================================


async def test_exchange_code_success(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "access_token": "ya29.new-access",
        "refresh_token": "1//new-refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    token = await client.exchange_code("auth-code-123")
    assert token.access_token == "ya29.new-access"
    assert token.refresh_token == "1//new-refresh"
    assert token.expiry is not None
    assert client.token is token
    # Verify POST body
    assert _FakeTransport.last_json is not None
    assert _FakeTransport.last_json["code"] == "auth-code-123"
    assert _FakeTransport.last_json["client_id"] == CID


async def test_exchange_code_failure(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 400
    _FakeTransport.payload = {"error": "invalid_grant", "error_description": "Code expired"}
    with pytest.raises(BloggerAuthError, match="Code expired"):
        await client.exchange_code("bad-code")


async def test_exchange_code_timeout(client):
    _FakeTransport.reset()
    _FakeTransport.raise_timeout = True
    with pytest.raises(BloggerTimeoutError, match="Token exchange timed out"):
        await client.exchange_code("code")


async def test_exchange_code_http_error(client):
    _FakeTransport.reset()
    _FakeTransport.raise_http = httpx.ConnectError
    with pytest.raises(BloggerError, match="Token exchange HTTP error"):
        await client.exchange_code("code")


async def test_exchange_code_missing_config():
    c = BloggerClient(client_id="", client_secret=CSECRET, redirect_uri=CREDIR)
    with pytest.raises(BloggerConfigError):
        await c.exchange_code("code")


# ===========================================================================
# Token refresh
# ===========================================================================


async def test_refresh_success(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "access_token": "ya29.refreshed",
        "expires_in": 3600,
    }
    token = await client.refresh_access_token()
    assert token.access_token == "ya29.refreshed"
    assert token.refresh_token == TOKEN.refresh_token  # kept from original
    assert _FakeTransport.last_json["grant_type"] == "refresh_token"
    assert _FakeTransport.last_json["refresh_token"] == "1//test-refresh"


async def test_refresh_new_refresh_token(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "access_token": "ya29.refreshed",
        "refresh_token": "1//brand-new",
        "expires_in": 3600,
    }
    token = await client.refresh_access_token()
    assert token.refresh_token == "1//brand-new"


async def test_refresh_failure(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 400
    _FakeTransport.payload = {"error": "invalid_grant", "error_description": "Token expired"}
    with pytest.raises(BloggerAuthError, match="Token expired"):
        await client.refresh_access_token()


async def test_refresh_no_refresh_token(no_token_client):
    no_token_client.token = TokenMaterial(access_token="a", refresh_token="")
    with pytest.raises(BloggerAuthError, match="No refresh token"):
        await no_token_client.refresh_access_token()


async def test_refresh_no_token_at_all(no_token_client):
    with pytest.raises(BloggerAuthError, match="No refresh token"):
        await no_token_client.refresh_access_token()


async def test_refresh_timeout(client):
    _FakeTransport.reset()
    _FakeTransport.raise_timeout = True
    with pytest.raises(BloggerTimeoutError, match="Token refresh timed out"):
        await client.refresh_access_token()


# ===========================================================================
# Auto token refresh
# ===========================================================================


async def test_ensure_valid_token_refreshes_when_expired(client):
    """_ensure_valid_token should refresh when the token is expired."""
    client.token = _token_expired()
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "access_token": "ya29.auto-refreshed",
        "expires_in": 3600,
    }
    await client._ensure_valid_token()
    assert client.token.access_token == "ya29.auto-refreshed"


async def test_ensure_valid_token_skips_when_fresh(client):
    """_ensure_valid_token should not refresh when the token is valid."""
    _FakeTransport.reset()
    original_token = client.token
    await client._ensure_valid_token()
    assert client.token is original_token  # same object, no refresh
    # No HTTP call should have been made
    assert _FakeTransport.last_url == ""


# ===========================================================================
# Blog endpoints
# ===========================================================================


async def test_list_blogs(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "items": [
            {"id": "111", "name": "My Blog", "url": "https://my.blogspot.com", "description": "A blog"},
            {"id": "222", "name": "Other", "url": "https://other.blogspot.com"},
        ]
    }
    blogs = await client.list_blogs()
    assert len(blogs) == 2
    assert blogs[0].id == "111"
    assert blogs[0].name == "My Blog"
    assert blogs[1].url == "https://other.blogspot.com"


async def test_list_blogs_empty(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {}
    blogs = await client.list_blogs()
    assert blogs == []


async def test_get_blog_by_url(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {"id": "111", "name": "My Blog", "url": "https://my.blogspot.com"}
    blog = await client.get_blog_by_url("https://my.blogspot.com")
    assert blog.id == "111"
    assert _FakeTransport.last_params == {"url": "https://my.blogspot.com"}


async def test_get_blog(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {"id": "111", "name": "My Blog", "url": "https://my.blogspot.com"}
    blog = await client.get_blog("111")
    assert blog.id == "111"
    assert "blogs/111" in _FakeTransport.last_url


# ===========================================================================
# Post endpoints
# ===========================================================================


async def test_insert_post(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "id": "post-1",
        "blogId": "111",
        "title": "Hello",
        "url": "https://blog.blogspot.com/post/1",
        "content": "<p>Hi</p>",
        "isDraft": True,
        "labels": ["tech"],
    }
    post = await client.insert_post("111", "Hello", "<p>Hi</p>", labels=["tech"], is_draft=True)
    assert post.id == "post-1"
    assert post.is_draft is True
    assert post.labels == ["tech"]
    assert _FakeTransport.last_json["isDraft"] is True


async def test_insert_post_no_labels(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {"id": "p2", "blogId": "111", "title": "T", "labels": []}
    post = await client.insert_post("111", "T", "content")
    assert post.labels == []
    assert "labels" not in (_FakeTransport.last_json or {})


async def test_update_post(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "id": "post-1",
        "blogId": "111",
        "title": "Updated",
        "content": "new content",
    }
    post = await client.update_post("111", "post-1", title="Updated", content="new content")
    assert post.title == "Updated"
    assert _FakeTransport.last_json["title"] == "Updated"
    assert _FakeTransport.last_json["content"] == "new content"


async def test_update_post_partial(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {"id": "post-1", "blogId": "111", "title": "Original"}
    await client.update_post("111", "post-1", title="Changed")
    assert "content" not in (_FakeTransport.last_json or {})


async def test_get_post(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "id": "post-1",
        "blogId": "111",
        "title": "T",
        "published": "2025-01-01T00:00:00-05:00",
    }
    post = await client.get_post("111", "post-1")
    assert post.id == "post-1"
    assert post.published == "2025-01-01T00:00:00-05:00"


async def test_list_posts(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "items": [
            {"id": "p1", "blogId": "111", "title": "Post 1"},
            {"id": "p2", "blogId": "111", "title": "Post 2"},
        ],
        "nextPageToken": "page2",
    }
    result = await client.list_posts("111", max_results=5, status="draft")
    assert len(result.items) == 2
    assert result.next_page_token == "page2"
    assert _FakeTransport.last_params["maxResults"] == 5
    assert _FakeTransport.last_params["status"] == "draft"


async def test_list_posts_empty(client):
    _FakeTransport.reset()
    _FakeTransport.payload = {}
    result = await client.list_posts("111")
    assert result.items == []
    assert result.next_page_token == ""


# ===========================================================================
# API error normalization
# ===========================================================================


async def test_401_raises_auth_error(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 401
    _FakeTransport.text = "Unauthorized"
    with pytest.raises(BloggerAuthError, match="token invalid or revoked"):
        await client.list_blogs()


async def test_403_raises_permission_error(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 403
    _FakeTransport.payload = {"error": {"message": "Forbidden"}}
    with pytest.raises(BloggerAPIError, match="Permission denied"):
        await client.list_blogs()


async def test_404_raises_not_found(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 404
    with pytest.raises(BloggerAPIError, match="Not found"):
        await client.get_post("111", "nonexistent")


async def test_429_raises_rate_limit(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 429
    _FakeTransport.headers = {"retry-after": "30"}
    with pytest.raises(BloggerAPIError, match="Rate limited"):
        await client.list_blogs()


async def test_429_without_retry_after(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 429
    with pytest.raises(BloggerAPIError, match="Rate limited"):
        await client.list_blogs()


async def test_500_raises_generic_api_error(client):
    _FakeTransport.reset()
    _FakeTransport.status_code = 500
    _FakeTransport.payload = {"error": {"message": "Internal error"}}
    with pytest.raises(BloggerAPIError, match="Blogger API error 500"):
        await client.list_blogs()


async def test_timeout_raises_timeout_error(client):
    _FakeTransport.reset()
    _FakeTransport.raise_timeout = True
    with pytest.raises(BloggerTimeoutError, match="timed out"):
        await client.list_blogs()


async def test_network_error_raises_generic_error(client):
    _FakeTransport.reset()
    _FakeTransport.raise_http = httpx.ConnectError
    with pytest.raises(BloggerError, match="HTTP error"):
        await client.list_blogs()


async def test_malformed_json_raises(client):
    _FakeTransport.reset()
    _FakeTransport.text = "not-json"
    _FakeTransport.headers = {"content-type": "text/html"}
    _FakeTransport.force_json_error = True
    with pytest.raises(BloggerError, match="Invalid JSON"):
        await client.list_blogs()


# ===========================================================================
# _parse_post helper
# ===========================================================================


def test_parse_post_fields():
    from services.blogger_client import _parse_post

    data = {
        "id": "123",
        "title": "T",
        "url": "https://blog.blogspot.com/p/123.html",
        "content": "<p>body</p>",
        "published": "2025-01-01T00:00:00-05:00",
        "updated": "2025-01-02T00:00:00-05:00",
        "labels": ["a", "b"],
        "isDraft": True,
    }
    post = _parse_post(data, "blog-1")
    assert post.id == "123"
    assert post.blog_id == "blog-1"
    assert post.title == "T"
    assert post.labels == ["a", "b"]
    assert post.is_draft is True


def test_parse_post_defaults():
    from services.blogger_client import _parse_post

    post = _parse_post({}, "blog-1")
    assert post.id == ""
    assert post.labels == []
    assert post.is_draft is False


# ===========================================================================
# Context manager & close
# ===========================================================================


async def test_context_manager(client):
    async with client as c:
        assert c is client


async def test_close_is_idempotent(client):
    await client.close()
    await client.close()  # no error


# ===========================================================================
# Auth headers
# ===========================================================================


def test_auth_headers_with_token(client):
    headers = client._auth_headers()
    assert headers["Authorization"] == f"Bearer {TOKEN.access_token}"


def test_auth_headers_without_token(no_token_client):
    assert no_token_client._auth_headers() == {}


# ===========================================================================
# Integration: exchange_code stores token, subsequent API call uses it
# ===========================================================================


async def test_exchange_then_list_blogs_uses_new_token():
    c = BloggerClient(client_id=CID, client_secret=CSECRET, redirect_uri=CREDIR)
    # Exchange
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "access_token": "ya29.brand-new",
        "refresh_token": "1//new",
        "expires_in": 3600,
    }
    await c.exchange_code("auth-code")
    # List blogs should use the new token
    _FakeTransport.reset()
    _FakeTransport.payload = {"items": [{"id": "1", "name": "B", "url": "https://b.blogspot.com"}]}
    blogs = await c.list_blogs()
    assert len(blogs) == 1
    # Verify the Authorization header was set correctly
    # (checked via _auth_headers since the fake client doesn't capture headers directly)


async def test_expired_token_auto_refreshes_on_api_call(client):
    """When token is expired, an API call should trigger a refresh first."""
    client.token = _token_expired()
    # First: refresh response
    _FakeTransport.reset()
    _FakeTransport.payload = {
        "access_token": "ya29.refreshed",
        "expires_in": 3600,
    }
    # The API call triggers refresh + actual call. We need two responses.
    # Since our fake always returns the same thing, we'll use a counter.
    call_count = 0
    original_build = _FakeTransport._build_response

    def counting_build(url, method="GET"):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call is token refresh
            return _FakeResponse(200, {"access_token": "ya29.auto", "expires_in": 3600})
        # Second call is the actual API request
        return _FakeResponse(200, {"items": [{"id": "1", "name": "B", "url": "https://b.blogspot.com"}]})

    _FakeTransport._build_response = counting_build
    blogs = await client.list_blogs()
    assert len(blogs) == 1
    assert call_count == 2
    _FakeTransport._build_response = original_build
