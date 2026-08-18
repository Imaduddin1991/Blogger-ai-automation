"""Blogger API v3 client with OAuth token management.

Single-user, single-blog for v1. Uses httpx for all HTTP calls (OAuth token
exchange + Blogger REST API). Token encryption at rest via Fernet
(cryptography library). No google-api-python-client — keeps dependencies
minimal.

Usage::

    async with BloggerClient(token=my_token) as client:
        blogs = await client.list_blogs()
        post = await client.insert_post(blog_id, title, html, is_draft=True)

All external calls are async and raise typed errors on failure. Tokens are
never logged. The client reads OAuth config from Settings (env / .env).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

# --- Constants --------------------------------------------------------------

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"

# --- Error hierarchy --------------------------------------------------------


class BloggerError(RuntimeError):
    """Base error for all Blogger client operations."""


class BloggerConfigError(BloggerError):
    """Missing or invalid Blogger configuration (client ID, secret, etc.)."""


class BloggerAuthError(BloggerError):
    """Authentication or authorization failure (expired/revoked token, denied consent)."""


class BloggerAPIError(BloggerError):
    """Blogger API returned a non-success HTTP status."""


class BloggerTimeoutError(BloggerError):
    """Request to Google/Blogger timed out."""


# --- Token model -----------------------------------------------------------


@dataclass
class TokenMaterial:
    """OAuth 2.0 token pair returned by Google's token endpoint."""

    access_token: str
    refresh_token: str
    expiry: datetime | None = None

    @property
    def is_expired(self) -> bool:
        """True when the access token is expired or within 60 s of expiry."""
        if self.expiry is None:
            return False
        return datetime.now(timezone.utc) >= self.expiry - timedelta(seconds=60)


# --- Blogger API response models -------------------------------------------


@dataclass
class BloggerBlog:
    """A Blogger blog resource (from blogs.get / blogs.getByUrl)."""

    id: str
    name: str
    url: str
    description: str = ""


@dataclass
class BloggerPost:
    """A Blogger post resource (from posts.get / posts.insert / posts.update)."""

    id: str
    blog_id: str
    title: str
    url: str = ""
    content: str = ""
    published: str = ""
    updated: str = ""
    labels: list[str] = field(default_factory=list)
    is_draft: bool = False


@dataclass
class PostListResponse:
    """Paginated list of Blogger posts."""

    items: list[BloggerPost]
    next_page_token: str = ""


# --- Token encryption at rest -----------------------------------------------


class TokenCryptor:
    """Fernet-based encrypt/decrypt for TokenMaterial stored in the database.

    Requires ``cryptography`` (Fernet). The key must be a URL-safe base64
    encoded 32-byte key (Fernet format).
    """

    def __init__(self, encryption_key: str) -> None:
        if not encryption_key:
            raise BloggerConfigError("ENCRYPTION_KEY not configured")
        from cryptography.fernet import Fernet

        key_bytes = (
            encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
        )
        self._fernet = Fernet(key_bytes)

    def encrypt_token(self, token: TokenMaterial) -> str:
        """Serialize and encrypt a token pair; returns a Fernet token string."""
        payload = json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expiry": token.expiry.isoformat() if token.expiry else None,
            }
        )
        return self._fernet.encrypt(payload.encode()).decode()

    def decrypt_token(self, encrypted: str) -> TokenMaterial:
        """Decrypt a Fernet token string back into TokenMaterial."""
        try:
            raw = json.loads(self._fernet.decrypt(encrypted.encode()))
        except Exception as exc:
            raise BloggerError("Failed to decrypt token") from exc
        expiry = (
            datetime.fromisoformat(raw["expiry"]) if raw.get("expiry") else None
        )
        return TokenMaterial(
            access_token=raw["access_token"],
            refresh_token=raw["refresh_token"],
            expiry=expiry,
        )


# --- Response parser --------------------------------------------------------


def _parse_post(data: dict[str, Any], blog_id: str) -> BloggerPost:
    """Parse a raw Blogger post JSON dict into a BloggerPost."""
    return BloggerPost(
        id=str(data.get("id", "")),
        blog_id=blog_id,
        title=data.get("title", ""),
        url=data.get("url", ""),
        content=data.get("content", ""),
        published=data.get("published", ""),
        updated=data.get("updated", ""),
        labels=data.get("labels", []),
        is_draft=data.get("isDraft", False),
    )


# --- Blogger client ---------------------------------------------------------


class BloggerClient:
    """Blogger API v3 client with transparent token refresh.

    Reads OAuth credentials from ``Settings`` (env / .env) by default.
    Pass explicit ``client_id`` / ``client_secret`` to override.

    All methods are async and raise ``BloggerError`` subclasses on failure.
    Tokens are never logged.
    """

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        redirect_uri: str = "",
        token: TokenMaterial | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.client_id = client_id or settings.blogger_client_id
        self.client_secret = client_secret or settings.blogger_client_secret
        self.redirect_uri = redirect_uri or settings.blogger_redirect_uri
        self.token = token
        self.timeout = timeout

    # --- Config guards ------------------------------------------------------

    def _ensure_configured(self) -> None:
        if not self.client_id:
            raise BloggerConfigError("BLOGGER_CLIENT_ID not configured")
        if not self.client_secret:
            raise BloggerConfigError("BLOGGER_CLIENT_SECRET not configured")

    def _ensure_authenticated(self) -> None:
        self._ensure_configured()
        if not self.token:
            raise BloggerAuthError("Not authenticated — no token available")

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token.access_token}"}

    # --- Lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        """Release resources (no-op for stateless httpx, kept for interface)."""

    async def __aenter__(self) -> BloggerClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # --- OAuth 2.0 flow -----------------------------------------------------

    def get_authorization_url(self, *, state: str | None = None) -> str:
        """Build the Google OAuth consent URL for Blogger access.

        Opens in the user's browser. Google redirects to ``redirect_uri``
        with an authorization code.
        """
        self._ensure_configured()
        params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": BLOGGER_SCOPE,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> TokenMaterial:
        """Exchange an authorization code for access + refresh tokens."""
        self._ensure_configured()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
        except httpx.TimeoutException as exc:
            raise BloggerTimeoutError("Token exchange timed out") from exc
        except httpx.HTTPError as exc:
            raise BloggerError(f"Token exchange HTTP error: {type(exc).__name__}") from exc

        if resp.status_code != 200:
            error_desc = _extract_error_desc(resp)
            raise BloggerAuthError(f"Token exchange failed: {error_desc}")

        data = resp.json()
        expiry = datetime.now(timezone.utc) + timedelta(
            seconds=data.get("expires_in", 3600)
        )
        token = TokenMaterial(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expiry=expiry,
        )
        self.token = token
        return token

    async def refresh_access_token(self) -> TokenMaterial:
        """Refresh the access token using the stored refresh token."""
        if not self.token or not self.token.refresh_token:
            raise BloggerAuthError("No refresh token available")
        self._ensure_configured()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "refresh_token": self.token.refresh_token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.TimeoutException as exc:
            raise BloggerTimeoutError("Token refresh timed out") from exc
        except httpx.HTTPError as exc:
            raise BloggerError(f"Token refresh HTTP error: {type(exc).__name__}") from exc

        if resp.status_code != 200:
            error_desc = _extract_error_desc(resp)
            raise BloggerAuthError(f"Token refresh failed: {error_desc}")

        data = resp.json()
        expiry = datetime.now(timezone.utc) + timedelta(
            seconds=data.get("expires_in", 3600)
        )
        self.token = TokenMaterial(
            access_token=data["access_token"],
            # Google may or may not return a new refresh token
            refresh_token=data.get("refresh_token", self.token.refresh_token),
            expiry=expiry,
        )
        return self.token

    async def _ensure_valid_token(self) -> None:
        """Refresh the token if expired or about to expire."""
        if self.token and self.token.is_expired:
            await self.refresh_access_token()

    # --- Blogger REST API ---------------------------------------------------

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Blogger API v3.

        Transparently refreshes the token on expiry. Raises typed errors for
        every failure mode (401, 403, 404, 429, timeouts, malformed JSON).
        """
        self._ensure_authenticated()
        await self._ensure_valid_token()
        url = f"{BLOGGER_API_BASE}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    headers=self._auth_headers(),
                )
        except httpx.TimeoutException as exc:
            raise BloggerTimeoutError(
                f"Request timed out: {method} {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise BloggerError(
                f"Blogger API HTTP error: {type(exc).__name__}"
            ) from exc

        if resp.status_code == 401:
            raise BloggerAuthError("Authentication failed (token invalid or revoked)")
        if resp.status_code == 403:
            raise BloggerAPIError("Permission denied (insufficient Blogger permissions)")
        if resp.status_code == 404:
            raise BloggerAPIError(f"Not found: {path}")
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after", "")
            raise BloggerAPIError(
                f"Rate limited{f' (retry after {retry_after}s)' if retry_after else ''}"
            )
        if resp.status_code >= 400:
            error_msg = _extract_api_error(resp)
            raise BloggerAPIError(
                f"Blogger API error {resp.status_code}: {error_msg}"
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise BloggerError("Invalid JSON response from Blogger API") from exc

    # --- Blog endpoints -----------------------------------------------------

    async def list_blogs(self) -> list[BloggerBlog]:
        """List all blogs for the authenticated user."""
        data = await self._api_request("GET", "users/self/blogs")
        return [
            BloggerBlog(
                id=str(b["id"]),
                name=b.get("name", ""),
                url=b.get("url", ""),
                description=b.get("description", ""),
            )
            for b in data.get("items", [])
        ]

    async def get_blog_by_url(self, url: str) -> BloggerBlog:
        """Resolve a blog URL to its Blogger blog resource."""
        data = await self._api_request("GET", "blogs/byurl", params={"url": url})
        return BloggerBlog(
            id=str(data["id"]),
            name=data.get("name", ""),
            url=data.get("url", ""),
            description=data.get("description", ""),
        )

    async def get_blog(self, blog_id: str) -> BloggerBlog:
        """Get a blog by its ID (connection test)."""
        data = await self._api_request("GET", f"blogs/{blog_id}")
        return BloggerBlog(
            id=str(data["id"]),
            name=data.get("name", ""),
            url=data.get("url", ""),
            description=data.get("description", ""),
        )

    # --- Post endpoints -----------------------------------------------------

    async def insert_post(
        self,
        blog_id: str,
        title: str,
        content: str,
        *,
        labels: list[str] | None = None,
        is_draft: bool = False,
    ) -> BloggerPost:
        """Create a new post on Blogger (draft or live)."""
        payload: dict[str, Any] = {
            "title": title,
            "content": content,
            "isDraft": is_draft,
        }
        if labels:
            payload["labels"] = labels
        data = await self._api_request(
            "POST", f"blogs/{blog_id}/posts", json_data=payload
        )
        return _parse_post(data, blog_id)

    async def update_post(
        self,
        blog_id: str,
        post_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        labels: list[str] | None = None,
    ) -> BloggerPost:
        """Update an existing Blogger post (partial update)."""
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if labels is not None:
            payload["labels"] = labels
        data = await self._api_request(
            "PUT", f"blogs/{blog_id}/posts/{post_id}", json_data=payload
        )
        return _parse_post(data, blog_id)

    async def get_post(self, blog_id: str, post_id: str) -> BloggerPost:
        """Get a single post by ID."""
        data = await self._api_request("GET", f"blogs/{blog_id}/posts/{post_id}")
        return _parse_post(data, blog_id)

    async def list_posts(
        self,
        blog_id: str,
        *,
        max_results: int = 10,
        page_token: str | None = None,
        status: str = "live",
    ) -> PostListResponse:
        """List posts on a blog with pagination."""
        params: dict[str, Any] = {"maxResults": max_results, "status": status}
        if page_token:
            params["pageToken"] = page_token
        data = await self._api_request(
            "GET", f"blogs/{blog_id}/posts", params=params
        )
        items = [_parse_post(p, blog_id) for p in data.get("items", [])]
        return PostListResponse(
            items=items,
            next_page_token=data.get("nextPageToken", ""),
        )


# --- Internal helpers -------------------------------------------------------


def _extract_error_desc(resp: httpx.Response) -> str:
    """Extract an error description from a Google OAuth error response."""
    try:
        data = resp.json()
        return data.get("error_description", "") or data.get("error", "") or resp.text[:200]
    except Exception:
        return resp.text[:200]


def _extract_api_error(resp: httpx.Response) -> str:
    """Extract an error message from a Blogger API error response."""
    try:
        data = resp.json()
        return (
            data.get("error", {}).get("message", "")
            or data.get("error_description", "")
            or resp.text[:200]
        )
    except Exception:
        return resp.text[:200]


# --- Token refresh helpers -------------------------------------------------

# Tokens expiring within 5 minutes are proactively refreshed
_NEAR_EXPIRY_SECONDS = 300


def is_token_near_expiry(token: TokenMaterial) -> bool:
    """Return True if the token is expired or will expire within 5 minutes."""
    if token.is_expired:
        return True
    if token.expiry is None:
        return False
    remaining = (token.expiry - datetime.now(timezone.utc)).total_seconds()
    return remaining < _NEAR_EXPIRY_SECONDS


async def refresh_if_needed(token: TokenMaterial, *, client: BloggerClient | None = None) -> TokenMaterial:
    """Refresh the token if expired or near-expiry. Returns the (possibly new) token.

    If a BloggerClient is provided, it is reused; otherwise a fresh one is created.
    Raises BloggerAuthError if refresh fails (caller should set status=token_expired).
    """
    if not is_token_near_expiry(token):
        return token
    if not token.refresh_token:
        raise BloggerAuthError("No refresh token available")
    if client is None:
        client = BloggerClient(token=token)
    else:
        client.token = token
    return await client.refresh_access_token()
