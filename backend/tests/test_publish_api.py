"""Publish API endpoint tests (Phase 5E).

Covers: approval gate, state validation, connection checks, concurrent publish
blocking, successful publish request, error handling, response schemas,
credential leakage prevention, idempotent retry, content payload verification.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import os

_test_db = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db}"

from app.config import get_settings

get_settings.cache_clear()

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app  # noqa: E402
from db.base import Base, apply_publish_column_migrations, engine
from db.models import Article, BlogConnection, PublishJob, PublishLog
from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    DRAFTED,
    IMAGE_READY,
    PUBLISHED,
    PUBLISH_FAILED,
    PUBLISHING,
    READY_FOR_REVIEW,
    transition,
)
from services.blogger_client import BloggerAPIError, BloggerAuthError, BloggerPost, BloggerTimeoutError, TokenMaterial


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _set_test_config(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "QgfJenhfUGGdtE4D55hvDZ70h4LHbsjmebD10qBN0RQ=")
    monkeypatch.setenv("BLOGGER_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("BLOGGER_CLIENT_SECRET", "test-client-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    apply_publish_column_migrations(engine)
    yield


@pytest.fixture(autouse=True)
def clear_runner():
    """Clear the serial runner pending set between tests to prevent cross-test contamination."""
    from services.runner import _pending
    _pending.clear()
    yield
    _pending.clear()


# --- Helpers -----------------------------------------------------------------


def _make_token():
    return TokenMaterial(
        access_token="ya29.access-token-test-value",
        refresh_token="1//refresh-token-test-value",
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _encrypt_token(token) -> str:
    from services.blogger_client import TokenCryptor
    settings = get_settings()
    return TokenCryptor(settings.encryption_key).encrypt_token(token)


def _seed_connection(db: Session, *, status="connected", blog_id="12345") -> BlogConnection:
    conn = BlogConnection(
        name="Test Blog",
        blog_id=blog_id,
        blog_url="https://test.blogspot.com",
        token_encrypted=_encrypt_token(_make_token()),
        status=status,
    )
    db.add(conn)
    db.commit()
    return conn


def _seed_article(
    db: Session,
    *,
    status=APPROVED,
    blog_id=None,
    body="Test article body content.",
    title="Test Article",
) -> Article:
    article = Article(
        idea_id=None,
        blog_id=blog_id,
        title=title,
        body=body,
        status=status,
        labels=["test"],
        word_count=5,
    )
    db.add(article)
    db.commit()
    return article


def _seed_publish_job(db: Session, article_id: int, *, status="running") -> PublishJob:
    job = PublishJob(
        article_id=article_id,
        run_at=datetime.now(timezone.utc),
        status=status,
        retry_count=0,
    )
    db.add(job)
    db.commit()
    return job


def _new_db():
    """Get a new session with expire_on_commit=False for test seeding."""
    return Session(engine, expire_on_commit=False)


def _publish_read(client, article_id, *, json=None):
    """POST to /api/articles/{id}/publish."""
    return client.post(f"/api/articles/{article_id}/publish", json=json or {})


def _draft_read(client, article_id):
    """POST to /api/articles/{id}/publish/draft."""
    return client.post(f"/api/articles/{article_id}/publish/draft")


def _retry_read(client, article_id):
    """POST to /api/articles/{id}/publish/retry."""
    return client.post(f"/api/articles/{article_id}/publish/retry")


# --- Approval gate tests -----------------------------------------------------


class TestApprovalGate:
    def test_draft_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=DRAFT, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"].lower()

    def test_checked_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=CHECKED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409

    def test_ready_for_review_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=READY_FOR_REVIEW, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409

    def test_image_ready_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=IMAGE_READY, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409

    def test_published_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISHED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409

    def test_publishing_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISHING, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409

    def test_publish_failed_rejected_by_publish_endpoint(self, client):
        """The /publish endpoint requires APPROVED; retry endpoint handles PUBLISH_FAILED."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISH_FAILED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"].lower()

    def test_drafted_rejected(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=DRAFTED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409


# --- Missing article ---------------------------------------------------------


class TestMissingArticle:
    def test_missing_article_404(self, client):
        resp = _publish_read(client, 9999)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# --- Connection checks --------------------------------------------------------


class TestConnectionChecks:
    def test_no_blog_connection(self, client):
        with _new_db() as db:
            article = _seed_article(db, status=APPROVED)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 400
        assert "blog connection" in resp.json()["detail"].lower()

    def test_disconnected_blog(self, client):
        with _new_db() as db:
            conn = _seed_connection(db, status="disconnected")
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 400
        assert "not connected" in resp.json()["detail"].lower()

    def test_missing_token(self, client):
        with _new_db() as db:
            conn = _seed_connection(db, status="connected")
            conn.token_encrypted = None
            db.commit()
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 400


# --- Successful publish request ----------------------------------------------


class TestSuccessfulPublish:
    def test_publish_approved_returns_202(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 202
        body = resp.json()
        assert body["id"] == article.id
        assert body["status"] == APPROVED

    def test_draft_returns_202(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _draft_read(client, article.id)
        assert resp.status_code == 202

    def test_retry_returns_202(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 202

    def test_as_draft_flag_passed(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id, json={"as_draft": True})
        assert resp.status_code == 202


# --- Publish failure / error responses ---------------------------------------


class TestPublishFailure:
    def test_retry_from_failed_reapproves(self, client):
        """retry on PUBLISH_FAILED article should re-approve and submit."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISH_FAILED, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 202
        # Verify the article was re-approved in the DB
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.status == APPROVED

    def test_retry_rejects_wrong_states(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISHED, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 409

    def test_retry_rejects_draft(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=DRAFT, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 409

    def test_draft_endpoint_rejects_non_approved(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=CHECKED, blog_id=conn.id)
        resp = _draft_read(client, article.id)
        assert resp.status_code == 409


# --- Already-running publish job / duplicate request --------------------------


class TestDuplicatePublish:
    def test_concurrent_publish_blocked_by_status(self, client):
        """PUBLISHING articles are rejected by the approval gate (not APPROVED)."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISHING, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"].lower()

    def test_concurrent_publish_blocked_by_runner_key(self, client):
        """When runner has a publish key pending, is_publish_running returns True."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        with patch("app.api.articles.is_publish_running", return_value=True):
            resp = _publish_read(client, article.id)
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"].lower()

    def test_publish_job_recorded_when_runner_pending(self, client):
        """When runner key is pending AND a DB job exists, publish is blocked."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
            _seed_publish_job(db, article.id, status="running")
        with patch("app.api.articles.is_publish_running", return_value=True):
            resp = _publish_read(client, article.id)
            assert resp.status_code == 409
        with _new_db() as db:
            job = db.scalars(
                select(PublishJob).where(PublishJob.article_id == article.id)
            ).first()
            assert job is not None
            assert job.status == "running"


# --- Response schema ---------------------------------------------------------


class TestResponseSchema:
    def test_response_has_required_fields(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        body = resp.json()
        assert "id" in body
        assert "status" in body
        assert "blogger_post_url" in body
        assert "blogger_published_at" in body

    def test_no_blogger_metadata_on_pending(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        body = resp.json()
        assert body["blogger_post_url"] is None
        assert body["blogger_published_at"] is None


# --- Safe error serialization ------------------------------------------------


class TestSafeErrorSerialization:
    def test_error_response_is_json(self, client):
        resp = _publish_read(client, 9999)
        assert resp.headers["content-type"].startswith("application/json")

    def test_409_detail_is_string(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=DRAFT, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert isinstance(resp.json()["detail"], str)

    def test_400_detail_is_string(self, client):
        with _new_db() as db:
            article = _seed_article(db, status=APPROVED)
        resp = _publish_read(client, article.id)
        assert isinstance(resp.json()["detail"], str)


# --- Credential leakage prevention -------------------------------------------


class TestCredentialLeakage:
    def test_token_not_in_409_response(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=DRAFT, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        body_text = resp.text
        assert "ya29" not in body_text

    def test_token_not_in_400_response(self, client):
        with _new_db() as db:
            article = _seed_article(db, status=APPROVED)
        resp = _publish_read(client, article.id)
        body_text = resp.text
        assert "ya29" not in body_text
        assert "refresh-token" not in body_text

    def test_encryption_key_not_exposed(self, client):
        with _new_db() as db:
            article = _seed_article(db, status=APPROVED)
        resp = _publish_read(client, article.id)
        body_text = resp.text
        assert "QgfJenhfUGGdtE4D55hvDZ70h4LHbsjmebD10qBN0RQ=" not in body_text


# --- Idempotent retry / existing blogger_post_id -----------------------------


class TestIdempotentRetry:
    def test_retry_on_approved_with_existing_post_id(self, client):
        """Retry on an already-published article should submit successfully (idempotent update)."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
            article.blogger_post_id = "existing-post-id"
            article.blogger_post_url = "https://blog.example.com/existing"
            db.commit()
        resp = _retry_read(client, article.id)
        assert resp.status_code == 202
        body = resp.json()
        assert body["blogger_post_url"] == "https://blog.example.com/existing"

    def test_publish_on_approved_without_post_id(self, client):
        """First publish (no existing post_id) should submit successfully."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 202
        assert resp.json()["blogger_post_url"] is None


# --- Content payload verification -------------------------------------------


class TestContentPayload:
    def test_article_body_available_in_db(self, client):
        """Verify the article body is available for the publish service to build content."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(
                db, status=APPROVED, blog_id=conn.id,
                body="<h1>Test</h1><p>Body content</p>",
            )
        resp = _publish_read(client, article.id)
        assert resp.status_code == 202
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.body == "<h1>Test</h1><p>Body content</p>"

    def test_labels_available_in_db(self, client):
        """Labels are persisted and available for the publish service."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
            article.labels = ["tech", "ai"]
            db.commit()
        resp = _publish_read(client, article.id)
        assert resp.status_code == 202
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.labels == ["tech", "ai"]

    def test_seo_title_available_in_db(self, client):
        """SEO title is persisted and available for the publish service."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
            article.seo_title = "SEO Optimized Title"
            db.commit()
        resp = _publish_read(client, article.id)
        assert resp.status_code == 202


# --- Approval gate remains intact --------------------------------------------


class TestApprovalGateIntact:
    def test_publish_does_not_approve(self, client):
        """Publishing an approved article does NOT create a new approval event."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
            assert article.review_approved_at is None
        _publish_read(client, article.id)
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.review_approved_at is None

    def test_selecting_images_still_does_not_approve(self, client):
        """Selecting images never approves an article (regression guard)."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=IMAGE_READY, blog_id=conn.id)
            from db.models import Image
            img = Image(
                article_id=article.id,
                provider="test",
                url="https://example.com/img.jpg",
                alt="test",
                position=1,
                status="candidate",
            )
            db.add(img)
            db.commit()
            image_id = img.id
        resp = client.post(f"/api/articles/{article.id}/images/{image_id}/select")
        assert resp.status_code == 200
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.status == IMAGE_READY  # Not approved

    def test_publish_endpoint_never_transitions_to_approved(self, client):
        """The publish endpoint is an invocation mechanism, not an approval mechanism."""
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISH_FAILED, blog_id=conn.id)
        resp = _publish_read(client, article.id)
        assert resp.status_code == 409
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.status == PUBLISH_FAILED  # Unchanged


# --- Draft endpoint tests ----------------------------------------------------


class TestDraftEndpoint:
    def test_draft_requires_approved(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=CHECKED, blog_id=conn.id)
        resp = _draft_read(client, article.id)
        assert resp.status_code == 409

    def test_draft_submit(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _draft_read(client, article.id)
        assert resp.status_code == 202

    def test_draft_blocks_concurrent(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISHING, blog_id=conn.id)
        resp = _draft_read(client, article.id)
        assert resp.status_code == 409


# --- Retry endpoint tests ----------------------------------------------------


class TestRetryEndpoint:
    def test_retry_approved(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 202

    def test_retry_publish_failed(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISH_FAILED, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 202
        with _new_db() as db:
            refreshed = db.get(Article, article.id)
            assert refreshed.status == APPROVED

    def test_retry_blocks_on_publishing(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=PUBLISHING, blog_id=conn.id)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 409

    def test_retry_missing_connection(self, client):
        with _new_db() as db:
            article = _seed_article(db, status=APPROVED)
        resp = _retry_read(client, article.id)
        assert resp.status_code == 400


# --- Publish background job invocation verification ---------------------------


class TestBackgroundJobInvocation:
    def test_publish_calls_start_background(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        with patch("app.api.articles.start_background_publish") as mock_bg:
            _publish_read(client, article.id)
            mock_bg.assert_called_once_with(article.id, as_draft=False)

    def test_draft_calls_start_background_as_draft(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        with patch("app.api.articles.start_background_publish") as mock_bg:
            _draft_read(client, article.id)
            mock_bg.assert_called_once_with(article.id, as_draft=True)

    def test_retry_calls_start_background(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        with patch("app.api.articles.start_background_publish") as mock_bg:
            _retry_read(client, article.id)
            mock_bg.assert_called_once_with(article.id, as_draft=False)

    def test_publish_with_as_draft_true(self, client):
        with _new_db() as db:
            conn = _seed_connection(db)
            article = _seed_article(db, status=APPROVED, blog_id=conn.id)
        with patch("app.api.articles.start_background_publish") as mock_bg:
            _publish_read(client, article.id, json={"as_draft": True})
            mock_bg.assert_called_once_with(article.id, as_draft=True)
