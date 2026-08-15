"""Database engine, session, and schema initialization (SQLite WAL)."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_for(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def _ensure_data_dir(url: str) -> None:
    if url.startswith("sqlite:///./") or url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1).split("?", 1)[0]
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


_settings = get_settings()
_ensure_data_dir(_settings.database_url)
engine = _engine_for(_settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _apply_sqlite_index_workarounds() -> None:
    """Create constraints that SQLite can't add via ALTER on existing DBs.

    Fresh DBs get these from Base.metadata.create_all(); older databases need
    the same constraints applied idempotently here.
    """
    if not _settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        dupes = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM (SELECT idea_id FROM articles "
            "WHERE idea_id IS NOT NULL GROUP BY idea_id HAVING COUNT(*) > 1)"
        ).scalar()
        if dupes:
            print("WARNING: articles has duplicate idea_id rows; skipping unique index")
            return
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_articles_idea_id "
            "ON articles(idea_id)"
        )


def init_db() -> None:
    from db import models  # noqa: F401  (register models on Base)

    Base.metadata.create_all(engine)
    _apply_sqlite_index_workarounds()
