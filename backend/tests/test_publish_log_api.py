"""Publish log API endpoint tests (Phase 6A).

Covers: list all logs, per-article logs, 404 for missing article, list jobs,
empty states, enrichment with article titles/URLs, ordering, auth guard.
"""

import tempfile
from datetime import datetime, timezone

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
from db.models import Article, PublishJob, PublishLog


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    apply_publish_column_migrations(engine)
    yield


@pytest.fixture(autouse=True)
def no_auth(monkeypatch):
    """Run without auth for most tests; individual auth tests set their own."""
    monkeypatch.delenv("LOCAL_AUTH_TOKEN", raising=False)
    get_settings.cache_clear()
    yield


# --- Helpers -----------------------------------------------------------------


def _new_db():
    return Session(engine, expire_on_commit=False)


def _seed_article(db: Session, *, title="Test Article", blogger_post_url=None) -> Article:
    article = Article(
        title=title,
        body="Body.",
        status="approved",
        labels=[],
        word_count=5,
        blogger_post_url=blogger_post_url,
    )
    db.add(article)
    db.commit()
    return article


def _seed_publish_log(
    db: Session,
    *,
    article_id=None,
    action="publish",
    result="success",
    details=None,
) -> PublishLog:
    log = PublishLog(
        article_id=article_id,
        action=action,
        result=result,
        details=details,
    )
    db.add(log)
    db.commit()
    return log


def _seed_publish_job(
    db: Session,
    *,
    article_id=None,
    status="pending",
    error=None,
) -> PublishJob:
    job = PublishJob(
        article_id=article_id,
        run_at=datetime.now(timezone.utc),
        status=status,
        error=error,
    )
    db.add(job)
    db.commit()
    return job


# --- GET /api/publish-log (list all) -----------------------------------------


class TestListPublishLog:
    def test_empty(self, client):
        resp = client.get("/api/publish-log")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_logs_newest_first(self, client):
        with _new_db() as db:
            article = _seed_article(db)
            log1 = _seed_publish_log(db, article_id=article.id, action="publish", result="success")
            log2 = _seed_publish_log(db, article_id=article.id, action="retry", result="error")
        resp = client.get("/api/publish-log")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["action"] == "retry"
        assert data[1]["action"] == "publish"

    def test_enriches_with_article_title(self, client):
        with _new_db() as db:
            article = _seed_article(db, title="My Blog Post")
            _seed_publish_log(db, article_id=article.id)
        resp = client.get("/api/publish-log")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["article_title"] == "My Blog Post"

    def test_enriches_with_blogger_url(self, client):
        with _new_db() as db:
            article = _seed_article(db, blogger_post_url="https://blog.example.com/post")
            _seed_publish_log(db, article_id=article.id)
        resp = client.get("/api/publish-log")
        data = resp.json()
        assert data[0]["blogger_post_url"] == "https://blog.example.com/post"

    def test_null_article_id_log(self, client):
        with _new_db() as db:
            _seed_publish_log(db, article_id=None, action="connection_test", result="success")
        resp = client.get("/api/publish-log")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["article_id"] is None
        assert data[0]["article_title"] is None

    def test_details_preserved(self, client):
        with _new_db() as db:
            _seed_publish_log(db, details={"error": "timeout", "code": 504})
        resp = client.get("/api/publish-log")
        data = resp.json()
        assert data[0]["details"] == {"error": "timeout", "code": 504}

    def test_response_schema(self, client):
        with _new_db() as db:
            _seed_publish_log(db, action="publish", result="success")
        resp = client.get("/api/publish-log")
        entry = resp.json()[0]
        assert set(entry.keys()) == {
            "id",
            "article_id",
            "article_title",
            "action",
            "result",
            "details",
            "blogger_post_url",
            "created_at",
        }


# --- GET /api/publish-log/article/{article_id} --------------------------------


class TestArticlePublishLog:
    def test_404_for_missing_article(self, client):
        resp = client.get("/api/publish-log/article/999")
        assert resp.status_code == 404

    def test_empty_for_article_with_no_logs(self, client):
        with _new_db() as db:
            article = _seed_article(db)
        resp = client.get(f"/api/publish-log/article/{article.id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_only_that_articles_logs(self, client):
        with _new_db() as db:
            art1 = _seed_article(db, title="Article 1")
            art2 = _seed_article(db, title="Article 2")
            _seed_publish_log(db, article_id=art1.id, action="publish")
            _seed_publish_log(db, article_id=art2.id, action="retry")
            _seed_publish_log(db, article_id=art1.id, action="update")
        resp = client.get(f"/api/publish-log/article/{art1.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(e["article_id"] == art1.id for e in data)

    def test_newest_first_ordering(self, client):
        with _new_db() as db:
            article = _seed_article(db)
            log1 = _seed_publish_log(db, article_id=article.id, action="publish")
            log2 = _seed_publish_log(db, article_id=article.id, action="update")
        resp = client.get(f"/api/publish-log/article/{article.id}")
        data = resp.json()
        assert data[0]["action"] == "update"
        assert data[1]["action"] == "publish"


# --- GET /api/publish-log/jobs -----------------------------------------------


class TestPublishJobs:
    def test_empty(self, client):
        resp = client.get("/api/publish-log/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_jobs_newest_first(self, client):
        with _new_db() as db:
            article = _seed_article(db)
            job1 = _seed_publish_job(db, article_id=article.id, status="completed")
            job2 = _seed_publish_job(db, article_id=article.id, status="failed")
        resp = client.get("/api/publish-log/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["status"] == "failed"
        assert data[1]["status"] == "completed"

    def test_enriches_with_article_title(self, client):
        with _new_db() as db:
            article = _seed_article(db, title="Scheduled Post")
            _seed_publish_job(db, article_id=article.id)
        resp = client.get("/api/publish-log/jobs")
        data = resp.json()
        assert data[0]["article_title"] == "Scheduled Post"

    def test_null_article_job(self, client):
        with _new_db() as db:
            _seed_publish_job(db, article_id=None, status="pending")
        resp = client.get("/api/publish-log/jobs")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["article_id"] is None
        assert data[0]["article_title"] is None

    def test_iso_timestamps(self, client):
        with _new_db() as db:
            _seed_publish_job(db, status="completed")
        resp = client.get("/api/publish-log/jobs")
        data = resp.json()
        assert "T" in data[0]["run_at"]  # ISO format contains T
        assert data[0]["published_at"] is None

    def test_response_schema(self, client):
        with _new_db() as db:
            _seed_publish_job(db, status="pending")
        resp = client.get("/api/publish-log/jobs")
        job = resp.json()[0]
        assert set(job.keys()) == {
            "id",
            "article_id",
            "article_title",
            "run_at",
            "status",
            "error",
            "retry_count",
            "published_at",
            "blogger_post_id",
        }


# --- Auth ---------------------------------------------------------------------


class TestPublishLogAuth:
    def test_unauthorized_when_token_set(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_AUTH_TOKEN", "secret-token")
        get_settings.cache_clear()
        resp = client.get("/api/publish-log")
        assert resp.status_code == 401

    def test_authorized_with_correct_token(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_AUTH_TOKEN", "secret-token")
        get_settings.cache_clear()
        resp = client.get("/api/publish-log", headers={"X-Auth-Token": "secret-token"})
        assert resp.status_code == 200

    def test_unauthorized_with_wrong_token(self, client, monkeypatch):
        monkeypatch.setenv("LOCAL_AUTH_TOKEN", "secret-token")
        get_settings.cache_clear()
        resp = client.get("/api/publish-log", headers={"X-Auth-Token": "wrong"})
        assert resp.status_code == 401
