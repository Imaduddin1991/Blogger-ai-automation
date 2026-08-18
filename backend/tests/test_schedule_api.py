"""Schedule API endpoint tests (Phase 6B).

Covers: schedule creation, cancel, list, validation, edge cases.
"""

import tempfile
from datetime import datetime, timedelta, timezone

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
from db.models import Article, BlogConnection, PublishJob
from pipeline.state import APPROVED, DRAFTED, PUBLISH_FAILED, SCHEDULED


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


# --- Helpers -----------------------------------------------------------------


def _seed_article(
    db: Session,
    *,
    status=APPROVED,
    title="Test Article",
) -> Article:
    article = Article(
        idea_id=None,
        blog_id=None,
        title=title,
        body="Test body.",
        status=status,
        labels=[],
        word_count=3,
    )
    db.add(article)
    db.commit()
    return article


def _seed_pending_job(db: Session, article_id: int, run_at: datetime) -> PublishJob:
    job = PublishJob(
        article_id=article_id,
        run_at=run_at,
        status="pending",
    )
    db.add(job)
    db.commit()
    return job


def _new_db() -> Session:
    return SessionLocal()


from db.base import SessionLocal


# --- Tests -------------------------------------------------------------------


class TestScheduleArticle:
    def test_schedule_approved_article(self, client):
        db = _new_db()
        article = _seed_article(db, status=APPROVED)
        run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        resp = client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["article_id"] == article.id
        assert data["status"] == "pending"
        assert "run_at" in data
        assert "job_id" in data

    def test_schedule_rejects_non_approved(self, client):
        db = _new_db()
        article = _seed_article(db, status=DRAFTED)
        run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        resp = client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        assert resp.status_code == 409

    def test_schedule_rejects_past_date(self, client):
        db = _new_db()
        article = _seed_article(db, status=APPROVED)
        run_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        resp = client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        assert resp.status_code == 400
        assert "future" in resp.json()["detail"]

    def test_schedule_rejects_too_far_future(self, client):
        db = _new_db()
        article = _seed_article(db, status=APPROVED)
        run_at = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()

        resp = client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        assert resp.status_code == 400
        assert "30 days" in resp.json()["detail"]

    def test_schedule_cancels_existing_pending_jobs(self, client):
        db = _new_db()
        article = _seed_article(db, status=APPROVED)
        old_job = _seed_pending_job(db, article.id, datetime.now(timezone.utc) + timedelta(hours=2))
        run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        resp = client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        assert resp.status_code == 201

        # Old job should be cancelled
        db.refresh(old_job)
        assert old_job.status == "cancelled"

    def test_schedule_article_state_transitions(self, client):
        db = _new_db()
        article = _seed_article(db, status=APPROVED)
        run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        db.refresh(article)
        assert article.status == SCHEDULED


class TestCancelSchedule:
    def _setup_scheduled(self, client, db):
        article = _seed_article(db, status=APPROVED)
        run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},

        )
        db.refresh(article)
        return article

    def test_cancel_schedule(self, client):
        db = _new_db()
        article = self._setup_scheduled(client, db)

        resp = client.delete(
            f"/api/articles/{article.id}/schedule",

        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        db.refresh(article)
        assert article.status == APPROVED

    def test_cancel_rejects_non_scheduled(self, client):
        db = _new_db()
        article = _seed_article(db, status=APPROVED)

        resp = client.delete(
            f"/api/articles/{article.id}/schedule",

        )
        assert resp.status_code == 409

    def test_cancel_article_state_returns_to_approved(self, client):
        db = _new_db()
        article = self._setup_scheduled(client, db)

        client.delete(
            f"/api/articles/{article.id}/schedule",

        )
        db.refresh(article)
        assert article.status == APPROVED


class TestListScheduled:
    def test_empty_list(self, client):
        resp = client.get("/api/scheduled", headers={"Authorization": "Bearer test-token"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_scheduled_articles(self, client):
        db = _new_db()
        article1 = _seed_article(db, status=APPROVED, title="Article 1")
        article2 = _seed_article(db, status=APPROVED, title="Article 2")

        now = datetime.now(timezone.utc)
        client.post(
            f"/api/articles/{article1.id}/schedule",
            json={"run_at": (now + timedelta(hours=2)).isoformat()},

        )
        client.post(
            f"/api/articles/{article2.id}/schedule",
            json={"run_at": (now + timedelta(hours=1)).isoformat()},

        )

        resp = client.get("/api/scheduled", headers={"Authorization": "Bearer test-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Should be ordered by run_at ascending
        assert data[0]["run_at"] <= data[1]["run_at"]
        titles = {d["article_title"] for d in data}
        assert titles == {"Article 1", "Article 2"}


class TestScheduleAuth:
    def test_schedule_requires_auth(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_AUTH_TOKEN", "secret-token")
        get_settings.cache_clear()

        db = _new_db()
        article = _seed_article(db, status=APPROVED)
        run_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        resp = client.post(
            f"/api/articles/{article.id}/schedule",
            json={"run_at": run_at},
        )
        assert resp.status_code in (401, 403)

    def test_list_requires_auth(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_AUTH_TOKEN", "secret-token")
        get_settings.cache_clear()

        resp = client.get("/api/scheduled")
        assert resp.status_code in (401, 403)

    def test_cancel_requires_auth(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_AUTH_TOKEN", "secret-token")
        get_settings.cache_clear()

        db = _new_db()
        article = _seed_article(db, status=SCHEDULED)

        resp = client.delete(f"/api/articles/{article.id}/schedule")
        assert resp.status_code in (401, 403)
