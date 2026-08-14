"""Health endpoint: app, database, and Ollama availability."""

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.config import get_settings
from app.deps import require_local_token
from app.schemas.common import HealthRead
from db.base import engine

router = APIRouter(prefix="/api/health", tags=["health"], dependencies=[Depends(require_local_token)])


def _check_database() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def _check_ollama(settings) -> dict:
    try:
        r = httpx.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=2.0)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            return {"available": True, "url": settings.ollama_url, "models": models}
        return {"available": False, "url": settings.ollama_url, "detail": f"HTTP {r.status_code}"}
    except Exception as exc:  # network down, ollama not installed, etc.
        return {"available": False, "url": settings.ollama_url, "detail": type(exc).__name__}


@router.get("", response_model=HealthRead)
def health() -> HealthRead:
    """Sync def so FastAPI runs it in a worker thread (no event-loop block).

    Both the Ollama ping and the SQLite check are blocking I/O; a threadpool
    keeps them off the async loop.
    """
    settings = get_settings()
    return HealthRead(
        status="ok",
        app=settings.app_name,
        database=_check_database(),
        ollama=_check_ollama(settings),
    )
