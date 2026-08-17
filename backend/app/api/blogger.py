"""Blogger connection endpoints: OAuth flow, status, blog listing, disconnect.

Single-user, single-blog for v1. OAuth callback is a public endpoint
(no auth) because Google redirects the user's browser directly here.
All other endpoints require the local auth token.
"""

import hashlib
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import (
    BloggerBlogRead,
    BloggerConnectRead,
    BloggerStatusRead,
)
from db.base import get_db
from db.models import BlogConnection
from services.blogger_client import (
    BloggerAPIError,
    BloggerAuthError,
    BloggerClient,
    BloggerConfigError,
    BloggerError,
    BloggerTimeoutError,
)

router = APIRouter(
    prefix="/api/blogger",
    tags=["blogger"],
    dependencies=[Depends(require_local_token)],
)

# --- In-memory pending OAuth states (CSRF protection) -----------------------

_PENDING_STATES: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _cleanup_expired_states() -> None:
    """Evict expired CSRF state entries."""
    now = time.time()
    expired = [s for s, t in _PENDING_STATES.items() if now - t > _STATE_TTL_SECONDS]
    for s in expired:
        del _PENDING_STATES[s]


def _register_state(state: str) -> None:
    """Store a pending OAuth state with a TTL."""
    _cleanup_expired_states()
    _PENDING_STATES[state] = time.time()


def _consume_state(state: str) -> bool:
    """Return True and remove the state if valid and not expired; False otherwise."""
    ts = _PENDING_STATES.get(state)
    if ts is None:
        return False
    if time.time() - ts > _STATE_TTL_SECONDS:
        del _PENDING_STATES[state]
        return False
    del _PENDING_STATES[state]
    return True


def _make_state() -> str:
    """Generate a cryptographically random state token."""
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()[:32]
    return f"{token}.{digest}"


# --- Helpers ----------------------------------------------------------------


def _get_connection(db: Session) -> BlogConnection | None:
    """Get the existing BlogConnection row (there is only one for v1)."""
    return db.scalars(select(BlogConnection).order_by(BlogConnection.id)).first()


def _ensure_connection_row(db: Session) -> BlogConnection:
    """Return the existing connection row, creating one if needed."""
    conn = _get_connection(db)
    if conn is None:
        conn = BlogConnection(
            name="Blogger",
            status="disconnected",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
    return conn


# --- Endpoints --------------------------------------------------------------


@router.get("/status", response_model=BloggerStatusRead)
def get_blogger_status(
    db: Session = Depends(get_db),
) -> BloggerStatusRead:
    """Return the current Blogger connection status."""
    conn = _get_connection(db)
    if conn is None or conn.status == "disconnected":
        return BloggerStatusRead(connected=False, status="disconnected")

    # Decrypt the token to check expiry
    from app.config import get_settings
    from services.blogger_client import TokenCryptor

    settings = get_settings()
    token_encrypted = conn.token_encrypted or ""
    if not token_encrypted:
        return BloggerStatusRead(connected=False, status="disconnected")

    try:
        cryptor = TokenCryptor(settings.encryption_key)
        token = cryptor.decrypt_token(token_encrypted)
        if token.is_expired:
            return BloggerStatusRead(connected=False, status="token_expired")
        return BloggerStatusRead(
            connected=True,
            blog_id=conn.blog_id or "",
            blog_url=conn.blog_url or "",
            blog_name=conn.name or "",
            status="connected",
        )
    except BloggerError:
        return BloggerStatusRead(connected=False, status="disconnected")


@router.post("/connect", response_model=BloggerConnectRead)
def start_connect(
    db: Session = Depends(get_db),
) -> BloggerConnectRead:
    """Generate a Google OAuth URL and return it for the user to open in browser."""
    client = BloggerClient()
    state = _make_state()
    _register_state(state)
    auth_url = client.get_authorization_url(state=state)
    return BloggerConnectRead(auth_url=auth_url)


@router.get("/callback")
async def blogger_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """OAuth redirect handler — called by Google after user consent.

    This endpoint is PUBLIC (no auth) because Google redirects here directly.
    Validates the state parameter for CSRF protection.
    """
    # User denied consent
    if error:
        conn = _ensure_connection_row(db)
        conn.status = "disconnected"
        conn.last_error = f"OAuth denied: {error}"
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Authorization denied: {error}",
        )

    # Validate state (CSRF protection)
    if not state or not _consume_state(state):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state. Please try connecting again.",
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="No authorization code received",
        )

    # Exchange code for tokens
    client = BloggerClient()
    try:
        token = await client.exchange_code(code)
    except BloggerAuthError as exc:
        conn = _ensure_connection_row(db)
        conn.status = "disconnected"
        conn.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    except BloggerTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except BloggerError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Encrypt and persist
    from app.config import get_settings
    from services.blogger_client import TokenCryptor

    settings = get_settings()
    cryptor = TokenCryptor(settings.encryption_key)
    encrypted = cryptor.encrypt_token(token)

    conn = _ensure_connection_row(db)
    conn.token_encrypted = encrypted
    conn.status = "connected"
    conn.last_error = None
    db.commit()

    # Fetch blogs to auto-fill blog_id
    try:
        client.token = token
        blogs = await client.list_blogs()
        if blogs:
            # Match existing blog_id if set, otherwise use first
            chosen = blogs[0]
            for b in blogs:
                if b.id == conn.blog_id:
                    chosen = b
                    break
            conn.blog_id = chosen.id
            conn.blog_url = chosen.url
            conn.name = chosen.name
            db.commit()
    except (BloggerError, BloggerAuthError):
        pass  # Token works but blog fetch failed; still connected

    return {"status": "connected", "blog_id": conn.blog_id or ""}


@router.get("/blogs", response_model=list[BloggerBlogRead])
async def list_blogger_blogs(
    db: Session = Depends(get_db),
) -> list[BloggerBlogRead]:
    """List blogs for the connected Blogger account."""
    conn = _get_connection(db)
    if not conn or not conn.token_encrypted:
        raise HTTPException(status_code=400, detail="No Blogger account connected")

    from app.config import get_settings
    from services.blogger_client import TokenCryptor

    settings = get_settings()
    try:
        cryptor = TokenCryptor(settings.encryption_key)
        token = cryptor.decrypt_token(conn.token_encrypted)
    except BloggerError:
        raise HTTPException(status_code=500, detail="Failed to decrypt token")

    client = BloggerClient(token=token)
    try:
        blogs = await client.list_blogs()
    except BloggerAuthError as exc:
        conn.status = "disconnected"
        conn.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=401, detail=str(exc))
    except BloggerError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return [
        BloggerBlogRead(
            id=b.id,
            name=b.name,
            url=b.url,
            description=b.description,
        )
        for b in blogs
    ]


@router.post("/disconnect", response_model=BloggerStatusRead)
def disconnect_blogger(
    db: Session = Depends(get_db),
) -> BloggerStatusRead:
    """Disconnect the Blogger account (clear tokens and blog info)."""
    conn = _get_connection(db)
    if not conn or conn.status == "disconnected":
        return BloggerStatusRead(connected=False, status="disconnected")

    conn.token_encrypted = None
    conn.blog_id = None
    conn.blog_url = None
    conn.status = "disconnected"
    conn.last_error = None
    db.commit()
    return BloggerStatusRead(connected=False, status="disconnected")
