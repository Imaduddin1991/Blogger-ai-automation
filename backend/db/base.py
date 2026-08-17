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


# Additive Image columns added to pre-existing databases. Mirrors the
# Phase 4C SQLAlchemy model exactly; `Base.metadata.create_all()` only creates
# missing tables, so existing `images` tables need these added via ALTER.
_IMAGE_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("status", "VARCHAR(20) DEFAULT 'candidate'"),
    ("page_url", "VARCHAR(1000)"),
    ("author", "TEXT"),
    ("license_url", "VARCHAR(500)"),
    ("attribution_required", "BOOLEAN DEFAULT 0"),
    ("usage_notes", "TEXT"),
    ("thumb_url", "VARCHAR(1000)"),
    ("mime", "VARCHAR(50)"),
    ("width", "INTEGER"),
    ("height", "INTEGER"),
    ("file_size", "INTEGER"),
    ("relevance", "FLOAT DEFAULT 0.0"),
    ("retrieved_at", "DATETIME"),
    ("rejection_reason", "TEXT"),
)


def apply_image_column_migrations(engine) -> None:
    """Add the Phase 4C image columns to an existing `images` table.

    Idempotent: inspects `PRAGMA table_info(images)` and adds only missing
    columns. Existing rows keep their data; legacy attached images become
    `selected` (they were already attached) and get `retrieved_at` backfilled
    from `created_at`. No destructive operations, no data rewrite.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        try:
            existing = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(images)")
            }
        except Exception:
            return  # no images table yet; create_all will build it with the columns
        added_status = "status" not in existing
        added_retrieved = "retrieved_at" not in existing
        for name, ddl in _IMAGE_ADDED_COLUMNS:
            if name in existing:
                continue
            conn.exec_driver_sql(f"ALTER TABLE images ADD COLUMN {name} {ddl}")
        if added_status:
            conn.exec_driver_sql("UPDATE images SET status='selected'")
        if added_retrieved:
            conn.exec_driver_sql(
                "UPDATE images SET retrieved_at = created_at WHERE retrieved_at IS NULL"
            )


# Phase 5D columns for Blogger publishing — added to existing articles
# and publish_jobs tables via idempotent ALTER TABLE ADD COLUMN.
_ARTICLE_PUBLISH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("blogger_post_id", "VARCHAR(100)"),
    ("blogger_post_url", "VARCHAR(500)"),
    ("blogger_published_at", "DATETIME"),
    ("blogger_status", "VARCHAR(30)"),
)

_PUBLISHJOB_COLUMNS: tuple[tuple[str, str], ...] = (
    ("blogger_post_id", "VARCHAR(100)"),
)


def apply_publish_column_migrations(engine) -> None:
    """Add the Phase 5D Blogger-publishing columns to existing tables.

    Idempotent: inspects PRAGMA table_info and adds only missing columns.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, columns in [("articles", _ARTICLE_PUBLISH_COLUMNS),
                               ("publish_jobs", _PUBLISHJOB_COLUMNS)]:
            try:
                existing = {
                    row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
                }
            except Exception:
                continue
            for name, ddl in columns:
                if name in existing:
                    continue
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    from db import models  # noqa: F401  (register models on Base)

    Base.metadata.create_all(engine)
    _apply_sqlite_index_workarounds()
    apply_image_column_migrations(engine)
    apply_publish_column_migrations(engine)
