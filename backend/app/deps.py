"""Shared API dependencies (local auth guard)."""

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_local_token(
    x_auth_token: str | None = Header(default=None),
) -> None:
    """Require the configured token when LOCAL_AUTH_TOKEN is set.

    Default (empty token) means localhost single-user: no auth needed.
    When the app is bound beyond 127.0.0.1, set LOCAL_AUTH_TOKEN so every
    request must carry the header.
    """
    settings = get_settings()
    if not settings.local_auth_token:
        return
    if x_auth_token != settings.local_auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Auth-Token",
        )
