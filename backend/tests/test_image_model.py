"""Phase 4C: Image model extensions and the additive migration."""

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from db.base import Base, apply_image_column_migrations
from db.models import Article, Image
from pipeline.images.providers.base import ImageResult
from pipeline.images.service import image_result_to_row
from pipeline.images.status import (
    IMAGE_STATUS_CANDIDATE,
    IMAGE_STATUS_SELECTED,
    IMAGE_STATUSES,
)

_PHASE_4C_COLUMNS = {
    "status",
    "page_url",
    "author",
    "license_url",
    "attribution_required",
    "usage_notes",
    "thumb_url",
    "mime",
    "width",
    "height",
    "file_size",
    "relevance",
    "retrieved_at",
    "rejection_reason",
}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


def _article(db) -> Article:
    article = Article(title="Why solar panels work", body="Text")
    db.add(article)
    db.flush()
    return article


# --- Model: defaults and required fields -------------------------------------


def test_image_defaults(db):
    article = _article(db)
    image = Image(
        article_id=article.id,
        provider="commons",
        url="https://upload.wikimedia.org/wikipedia/commons/a.jpg",
    )
    db.add(image)
    db.commit()
    fresh = db.get(Image, image.id)
    assert fresh.status == IMAGE_STATUS_CANDIDATE
    assert fresh.attribution_required is False
    assert fresh.relevance == 0.0
    assert fresh.position == 0
    assert fresh.page_url is None
    assert fresh.created_at is not None
    assert fresh.updated_at is not None


def test_image_statuses_are_valid_set():
    assert IMAGE_STATUS_CANDIDATE in IMAGE_STATUSES
    assert IMAGE_STATUS_SELECTED in IMAGE_STATUSES


def test_image_requires_provider_and_url(db):
    for image in (Image(url="https://x/a.jpg"), Image(provider="commons")):
        db.add(image)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_image_relationship_and_cascade_delete(db):
    article = _article(db)
    image = Image(article_id=article.id, provider="commons", url="https://x/a.jpg")
    db.add(image)
    db.commit()
    assert db.get(Image, image.id).article.title == article.title
    db.delete(article)
    db.commit()
    assert db.get(Image, image.id) is None


def test_image_persists_phase_4c_metadata(db):
    article = _article(db)
    image = Image(
        article_id=article.id,
        provider="commons",
        url="https://upload.wikimedia.org/a.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:A.jpg",
        author="Jane Doe",
        license="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        attribution_required=True,
        usage_notes="Credit Jane Doe",
        thumb_url="https://upload.wikimedia.org/thumb/400px-a.jpg",
        mime="image/jpeg",
        width=1600,
        height=1200,
        file_size=234567,
        relevance=0.75,
        status=IMAGE_STATUS_SELECTED,
    )
    db.add(image)
    db.commit()
    fresh = db.get(Image, image.id)
    assert fresh.page_url == image.page_url
    assert fresh.attribution_required is True
    assert fresh.mime == "image/jpeg"
    assert fresh.width == 1600
    assert fresh.relevance == 0.75


# --- Migration ---------------------------------------------------------------


def _legacy_images_table(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE images ("
            "id INTEGER PRIMARY KEY, "
            "article_id INTEGER, "
            "provider VARCHAR(50) NOT NULL, "
            "url VARCHAR(1000) NOT NULL, "
            "alt TEXT, caption TEXT, attribution TEXT, license VARCHAR(100), "
            "position INTEGER DEFAULT 0, created_at DATETIME, updated_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO images (provider, url, created_at, updated_at) "
            "VALUES ('commons', 'https://upload.wikimedia.org/legacy.jpg', "
            "'2025-01-01 00:00:00', '2025-01-01 00:00:00')"
        )


def _legacy_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _legacy_images_table(engine)
    return engine


def test_fresh_schema_contains_phase_4c_columns(db):
    columns = {c["name"] for c in inspect(db.get_bind()).get_columns("images")}
    assert _PHASE_4C_COLUMNS <= columns


def test_migration_upgrades_legacy_table():
    engine = _legacy_engine()
    assert "status" not in {c["name"] for c in inspect(engine).get_columns("images")}

    apply_image_column_migrations(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("images")}
    assert _PHASE_4C_COLUMNS <= columns
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT status, retrieved_at FROM images").one()
    assert row[0] == IMAGE_STATUS_SELECTED  # legacy attached images stay selected
    assert row[1] is not None  # retrieved_at backfilled from created_at


def test_migration_is_idempotent():
    engine = _legacy_engine()
    apply_image_column_migrations(engine)
    apply_image_column_migrations(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("images")}
    assert _PHASE_4C_COLUMNS <= columns
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT status, retrieved_at FROM images").one()
    assert row[0] == IMAGE_STATUS_SELECTED  # second run must not touch statuses
    assert row[1] is not None


def test_migration_does_not_touch_rejected_rows_on_rerun():
    engine = _legacy_engine()
    apply_image_column_migrations(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE images SET status='rejected'")
    apply_image_column_migrations(engine)
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT status FROM images").one()
    assert row[0] == "rejected"


def test_migration_existing_rows_stay_usable():
    engine = _legacy_engine()
    apply_image_column_migrations(engine)
    with engine.connect() as conn:
        count = conn.exec_driver_sql("SELECT COUNT(*) FROM images").scalar_one()
    assert count == 1
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    fresh = session.scalars(select(Image).where(Image.provider == "commons")).one()
    assert fresh.url == "https://upload.wikimedia.org/legacy.jpg"
    assert fresh.status == IMAGE_STATUS_SELECTED
    session.close()


# --- ImageResult -> Image mapping -----------------------------------------------


def _result(**overrides) -> ImageResult:
    result = ImageResult(
        provider="commons",
        image_url="https://upload.wikimedia.org/wikipedia/commons/a.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:A.jpg",
        title="A cat",
        description="A cat lounging on a windowsill",
        author="Jane Doe",
        license="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        attribution_required=True,
        usage_notes="Credit Jane Doe",
        mime="image/jpeg",
        width=1600,
        height=1200,
        file_size=234567,
        relevance=0.9,
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def test_image_result_maps_to_row(db):
    article = _article(db)
    image = image_result_to_row(_result(), article_id=article.id)
    db.add(image)
    db.commit()
    fresh = db.get(Image, image.id)
    assert fresh.provider == "commons"
    assert fresh.url == "https://upload.wikimedia.org/wikipedia/commons/a.jpg"
    assert fresh.page_url == "https://commons.wikimedia.org/wiki/File:A.jpg"
    assert fresh.caption == "A cat"
    assert fresh.alt == "A cat lounging on a windowsill"
    assert fresh.author == "Jane Doe"
    assert fresh.license_url == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert fresh.attribution_required is True
    assert fresh.mime == "image/jpeg"
    assert fresh.width == 1600
    assert fresh.file_size == 234567
    assert fresh.relevance == 0.9
    assert fresh.status == IMAGE_STATUS_CANDIDATE


def test_image_result_rejects_unusable_record(db):
    with pytest.raises(ValueError) as excinfo:
        image_result_to_row(_result(license="CC BY-NC 4.0"))
    assert "license" in str(excinfo.value)


def test_image_result_row_always_has_retrieved_at(db):
    article = _article(db)
    image = image_result_to_row(_result(retrieved_at=None), article_id=article.id)
    db.add(image)
    db.commit()
    assert db.get(Image, image.id).retrieved_at is not None
