"""Publishing service tests (Phase 5D).

Covers: state gates, happy path, idempotent update, error handling,
content building, image embedding, security, audit logging, recovery.
"""

import asyncio
import logging

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.base import Base, apply_publish_column_migrations
from db.models import Article, BlogConnection, PublishJob, PublishLog
from pipeline.publish import (
    PublishError,
    _sanitize_error,
    publish_to_blogger,
    recover_stuck_publishing,
)
from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    IMAGE_READY,
    PUBLISHED,
    PUBLISH_FAILED,
    PUBLISHING,
    READY_FOR_REVIEW,
    transition,
)
from services.blogger_client import (
    BloggerAPIError,
    BloggerAuthError,
    BloggerClient,
    BloggerPost,
    BloggerTimeoutError,
    TokenMaterial,
)


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    apply_publish_column_migrations(engine)
    session_maker = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_maker()
    yield session
    session.close()


def _seed_article(db, *, status=APPROVED, with_connection=True, with_image=False):
    """Create a minimal article + blog connection for publish tests."""
    if with_connection:
        conn = BlogConnection(
            name="Test Blog",
            blog_id="123456",
            blog_url="https://test.blogspot.com",
            status="connected",
            token_encrypted="fake-encrypted-token",
        )
        db.add(conn)
        db.flush()
        blog_id_fk = conn.id
    else:
        blog_id_fk = None

    article = Article(
        title="Solar Panels Guide",
        body="## Introduction\n\nSolar panels convert sunlight into electricity.",
        slug="solar-panels-guide",
        seo_title="Solar Panels: A Complete Guide",
        meta_description="Learn how solar panels work.",
        labels=["solar", "energy"],
        word_count=50,
        status=status,
        blog_id=blog_id_fk,
    )
    db.add(article)
    db.flush()

    if with_image:
        from db.models import Image
        img = Image(
            article_id=article.id,
            provider="wikimedia",
            url="https://upload.wikimedia.org/solar.jpg",
            alt="Solar panel field",
            caption="A solar panel installation",
            attribution="Photo by John Doe / CC BY 4.0",
            license="CC BY 4.0",
            position=0,
            status="selected",
        )
        db.add(img)
    db.commit()
    db.refresh(article)
    return article


class _FakeBloggerClient:
    """Mock BloggerClient that records calls and returns configurable responses."""

    def __init__(
        self,
        *,
        post_id: str = "blogger-post-123",
        post_url: str = "https://test.blogspot.com/2025/01/post.html",
        insert_error: Exception | None = None,
        update_error: Exception | None = None,
    ):
        self.post_id = post_id
        self.post_url = post_url
        self.insert_error = insert_error
        self.update_error = update_error
        self.insert_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.get_post_calls: list[tuple[str, str]] = []
        self._get_post_result: BloggerPost | None = None

    async def insert_post(self, blog_id, title, content, *, labels=None, is_draft=False):
        self.insert_calls.append({
            "blog_id": blog_id,
            "title": title,
            "content": content,
            "labels": labels,
            "is_draft": is_draft,
        })
        if self.insert_error:
            raise self.insert_error
        return BloggerPost(
            id=self.post_id,
            blog_id=blog_id,
            title=title,
            url=self.post_url,
            content=content,
            labels=labels or [],
            is_draft=is_draft,
        )

    async def update_post(self, blog_id, post_id, *, title=None, content=None, labels=None):
        self.update_calls.append({
            "blog_id": blog_id,
            "post_id": post_id,
            "title": title,
            "content": content,
            "labels": labels,
        })
        if self.update_error:
            raise self.update_error
        return BloggerPost(
            id=post_id,
            blog_id=blog_id,
            title=title or "",
            url=self.post_url,
            content=content or "",
            labels=labels or [],
        )

    async def get_post(self, blog_id, post_id):
        self.get_post_calls.append((blog_id, post_id))
        if self._get_post_result:
            return self._get_post_result
        return BloggerPost(
            id=post_id,
            blog_id=blog_id,
            title="Existing Post",
            url=self.post_url,
            is_draft=False,
        )


# --- State gate tests --------------------------------------------------------


class TestStateGating:
    """Publishing must only be allowed from APPROVED state."""

    async def test_publish_from_approved_works(self, db):
        article = _seed_article(db, status=APPROVED)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        result = await publish_to_blogger(db, article, conn, client)

        assert result.status == PUBLISHED
        assert result.blogger_post_id == "blogger-post-123"

    async def test_publish_from_draft_rejected(self, db):
        article = _seed_article(db, status=DRAFT, with_connection=False)
        conn = BlogConnection(name="Test", blog_id="123", status="connected")
        db.add(conn)
        db.commit()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="must be 'approved'"):
            await publish_to_blogger(db, article, conn, client)

    async def test_publish_from_checked_rejected(self, db):
        article = _seed_article(db, status=CHECKED)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="must be 'approved'"):
            await publish_to_blogger(db, article, conn, client)

    async def test_publish_from_ready_for_review_rejected(self, db):
        article = _seed_article(db, status=READY_FOR_REVIEW)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="must be 'approved'"):
            await publish_to_blogger(db, article, conn, client)

    async def test_publish_from_publishing_rejected(self, db):
        article = _seed_article(db, status=PUBLISHING)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="must be 'approved'"):
            await publish_to_blogger(db, article, conn, client)

    async def test_publish_from_published_rejected(self, db):
        article = _seed_article(db, status=PUBLISHED)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="must be 'approved'"):
            await publish_to_blogger(db, article, conn, client)

    async def test_publish_from_publish_failed_rejected(self, db):
        """Cannot publish from PUBLISH_FAILED — must explicitly retry."""
        article = _seed_article(db, status=PUBLISH_FAILED)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="must be 'approved'"):
            await publish_to_blogger(db, article, conn, client)

    async def test_publish_requires_blog_id(self, db):
        article = _seed_article(db, status=APPROVED, with_connection=False)
        conn = BlogConnection(name="No Blog", status="connected", blog_id=None)
        db.add(conn)
        db.commit()
        client = _FakeBloggerClient()

        with pytest.raises(PublishError, match="No blog_id"):
            await publish_to_blogger(db, article, conn, client)


# --- Happy path tests --------------------------------------------------------


class TestHappyPath:
    """Successful publish flow: first publish, update, draft mode."""

    async def test_first_publish(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        result = await publish_to_blogger(db, article, conn, client)

        assert result.status == PUBLISHED
        assert result.blogger_post_id == "blogger-post-123"
        assert result.blogger_post_url == "https://test.blogspot.com/2025/01/post.html"
        assert result.blogger_published_at is not None
        assert result.blogger_status == "live"
        assert len(client.insert_calls) == 1
        assert len(client.update_calls) == 0

    async def test_publish_as_draft(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        result = await publish_to_blogger(db, article, conn, client, as_draft=True)

        assert result.status == PUBLISHED
        assert result.blogger_status == "draft"
        assert client.insert_calls[0]["is_draft"] is True

    async def test_republish_uses_update(self, db):
        """Article already has blogger_post_id → uses update_post, not insert."""
        article = _seed_article(db)
        article.blogger_post_id = "existing-post-id"
        db.commit()
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        result = await publish_to_blogger(db, article, conn, client)

        assert result.status == PUBLISHED
        assert result.blogger_post_id == "existing-post-id"
        assert len(client.update_calls) == 1
        assert client.update_calls[0]["post_id"] == "existing-post-id"
        assert len(client.insert_calls) == 0

    async def test_blogger_post_id_persisted(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(post_id="abc-456")

        result = await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == result.id)).one()
        assert fresh.blogger_post_id == "abc-456"

    async def test_blogger_post_url_persisted(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(post_url="https://blog.example.com/post")

        result = await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == result.id)).one()
        assert fresh.blogger_post_url == "https://blog.example.com/post"

    async def test_labels_passed_to_blogger(self, db):
        article = _seed_article(db)
        article.labels = ["solar", "renewable", "energy"]
        db.commit()
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        assert client.insert_calls[0]["labels"] == ["solar", "renewable", "energy"]


# --- Error handling tests ----------------------------------------------------


class TestErrorHandling:
    """Blogger API errors, timeouts, auth failures, and unexpected errors."""

    async def test_auth_error_sets_publish_failed(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(insert_error=BloggerAuthError("Token revoked"))

        with pytest.raises(PublishError, match="auth error"):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_api_error_sets_publish_failed(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(
            insert_error=BloggerAPIError("Permission denied (insufficient Blogger permissions)")
        )

        with pytest.raises(PublishError, match="API error"):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_timeout_sets_publish_failed(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(insert_error=BloggerTimeoutError("Request timed out"))

        with pytest.raises(PublishError, match="timeout"):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_403_error(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(
            insert_error=BloggerAPIError("Permission denied (insufficient Blogger permissions)")
        )

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_404_error(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(
            insert_error=BloggerAPIError("Not found: blogs/123456/posts")
        )

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_429_rate_limit_error(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(
            insert_error=BloggerAPIError("Rate limited (retry after 60s)")
        )

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_unexpected_exception(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(insert_error=RuntimeError("Disk full"))

        with pytest.raises(PublishError, match="Unexpected"):
            await publish_to_blogger(db, article, conn, client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

    async def test_error_recorded_on_job(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(insert_error=BloggerAPIError("Forbidden"))

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        job = db.scalars(
            select(PublishJob).where(PublishJob.article_id == article.id)
        ).first()
        assert job is not None
        assert job.status == "failed"
        assert "Forbidden" in (job.error or "")


# --- Audit logging tests -----------------------------------------------------


class TestAuditLogging:
    """PublishLog entries are created for success, failure, and recovery."""

    async def test_success_logged(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        logs = db.scalars(
            select(PublishLog).where(PublishLog.article_id == article.id)
        ).all()
        assert len(logs) == 1
        assert logs[0].action == "insert"
        assert logs[0].result == "success"
        assert logs[0].details["post_id"] == "blogger-post-123"

    async def test_update_logged(self, db):
        article = _seed_article(db)
        article.blogger_post_id = "existing-id"
        db.commit()
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        logs = db.scalars(
            select(PublishLog).where(PublishLog.article_id == article.id)
        ).all()
        assert logs[0].action == "update"

    async def test_failure_logged(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(insert_error=BloggerAPIError("Oops"))

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        logs = db.scalars(
            select(PublishLog).where(PublishLog.article_id == article.id)
        ).all()
        assert len(logs) == 1
        assert logs[0].result == "failure"
        assert "Oops" in logs[0].details["error"]


# --- Content payload tests ---------------------------------------------------


class TestContentPayload:
    """Content is built through Phase 5C and passed to Blogger API."""

    async def test_content_includes_body(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        content = client.insert_calls[0]["content"]
        assert "Solar panels convert sunlight" in content

    async def test_content_includes_title(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        title = client.insert_calls[0]["title"]
        assert title == "Solar Panels: A Complete Guide"

    async def test_content_includes_images(self, db):
        article = _seed_article(db, with_image=True)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        content = client.insert_calls[0]["content"]
        assert "https://upload.wikimedia.org/solar.jpg" in content
        assert "Solar panel field" in content

    async def test_selected_images_only(self, db):
        article = _seed_article(db)
        from db.models import Image
        # Add a selected image
        sel = Image(
            article_id=article.id, provider="w", url="https://a.com/sel.jpg",
            alt="selected", position=0, status="selected",
        )
        # Add a candidate image (should be excluded)
        cand = Image(
            article_id=article.id, provider="w", url="https://a.com/cand.jpg",
            alt="candidate", position=1, status="candidate",
        )
        db.add_all([sel, cand])
        db.commit()
        db.refresh(article)

        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        content = client.insert_calls[0]["content"]
        assert "sel.jpg" in content
        assert "cand.jpg" not in content

    async def test_unsafe_urls_sanitized_in_content(self, db):
        article = _seed_article(db)
        from db.models import Image
        img = Image(
            article_id=article.id, provider="w",
            url="javascript:alert(1)", alt="evil", position=0, status="selected",
        )
        db.add(img)
        db.commit()
        db.refresh(article)

        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        content = client.insert_calls[0]["content"]
        assert "javascript:" not in content

    async def test_seo_title_used_when_available(self, db):
        article = _seed_article(db)
        article.seo_title = "Best Solar Panels 2025"
        db.commit()
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        assert client.insert_calls[0]["title"] == "Best Solar Panels 2025"

    async def test_fallback_to_title_when_no_seo_title(self, db):
        article = _seed_article(db)
        article.seo_title = None
        db.commit()
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        assert client.insert_calls[0]["title"] == "Solar Panels Guide"


# --- Security tests ----------------------------------------------------------


class TestSecurity:
    """OAuth tokens never appear in logs or persisted error messages."""

    async def test_token_not_in_error_messages(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        # Simulate an error that might contain token-like strings
        client = _FakeBloggerClient(
            insert_error=BloggerAPIError(
                "Auth failed with token gAAAAABk1234567890abcdefghijklmnop.abcdefghij"
            )
        )

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        job = db.scalars(
            select(PublishJob).where(PublishJob.article_id == article.id)
        ).first()
        assert "gAAAAABk" not in (job.error or "")
        assert "REDACTED" in (job.error or "")

    async def test_sanitize_error_removes_fernet_tokens(self):
        msg = "Error with token gAAAAABk1234567890abcdefghijklmnop.abcdefghij1234"
        result = _sanitize_error(msg)
        assert "gAAAAABk" not in result
        assert "REDACTED" in result

    async def test_sanitize_error_removes_bearer_tokens(self):
        msg = "Bearer eyJhbGciOiJIUzI1NiJ9.test"
        result = _sanitize_error(msg)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "Bearer [REDACTED]" in result

    async def test_sanitize_error_preserves_normal_text(self):
        msg = "Permission denied (insufficient Blogger permissions)"
        result = _sanitize_error(msg)
        assert result == msg


# --- PublishJob tracking -----------------------------------------------------


class TestPublishJobTracking:
    """PublishJob is created, updated, and tracks retry count."""

    async def test_job_created_on_publish(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient()

        await publish_to_blogger(db, article, conn, client)

        job = db.scalars(
            select(PublishJob).where(PublishJob.article_id == article.id)
        ).first()
        assert job is not None
        assert job.status == "completed"
        assert job.blogger_post_id == "blogger-post-123"
        assert job.published_at is not None

    async def test_job_records_failure(self, db):
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()
        client = _FakeBloggerClient(insert_error=BloggerAPIError("Oops"))

        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, client)

        job = db.scalars(
            select(PublishJob).where(PublishJob.article_id == article.id)
        ).first()
        assert job.status == "failed"
        assert "Oops" in (job.error or "")

    async def test_retry_after_failure_succeeds(self, db):
        """After a failed publish, a retry with fixed client succeeds."""
        article = _seed_article(db)
        conn = db.scalars(select(BlogConnection)).first()

        # First attempt: fails
        bad_client = _FakeBloggerClient(insert_error=BloggerAPIError("Temporary error"))
        with pytest.raises(PublishError):
            await publish_to_blogger(db, article, conn, bad_client)

        fresh = db.scalars(select(Article).where(Article.id == article.id)).one()
        assert fresh.status == PUBLISH_FAILED

        # Simulate retry: reset status to APPROVED, try again
        article.status = APPROVED
        db.commit()

        good_client = _FakeBloggerClient()
        result = await publish_to_blogger(db, article, conn, good_client)

        assert result.status == PUBLISHED
        assert result.blogger_post_id == "blogger-post-123"


# --- Recovery tests ----------------------------------------------------------


class TestRecovery:
    """recover_stuck_publishing handles stuck PUBLISHING rows."""

    async def test_recovery_transitions_to_publish_failed_when_no_post(self, db):
        article = _seed_article(db, status=PUBLISHING)
        client = _FakeBloggerClient()

        result = await recover_stuck_publishing(db, article, client)

        assert result.status == PUBLISH_FAILED

    async def test_recovery_with_existing_post_id(self, db, monkeypatch):
        article = _seed_article(db, status=PUBLISHING)
        article.blogger_post_id = "existing-post"
        db.commit()

        # Mock TokenCryptor to bypass real Fernet decryption in tests
        class _FakeCryptor:
            def decrypt_token(self, encrypted):
                return TokenMaterial(
                    access_token="fake-access",
                    refresh_token="fake-refresh",
                )

        monkeypatch.setattr(
            "services.blogger_client.TokenCryptor",
            lambda key: _FakeCryptor(),
        )

        client = _FakeBloggerClient()
        post = BloggerPost(
            id="existing-post", blog_id="123456", title="Test",
            url="https://blog.example.com/post", is_draft=False,
        )
        client._get_post_result = post

        result = await recover_stuck_publishing(db, article, client)

        assert result.status == PUBLISHED
        assert result.blogger_post_url == "https://blog.example.com/post"

    async def test_recovery_logs_event(self, db):
        article = _seed_article(db, status=PUBLISHING)
        client = _FakeBloggerClient()

        await recover_stuck_publishing(db, article, client)

        logs = db.scalars(
            select(PublishLog).where(PublishLog.article_id == article.id)
        ).all()
        assert len(logs) == 1
        assert logs[0].action == "recover"
        assert logs[0].result == "no_post_found"

    async def test_recovery_skips_non_publishing_articles(self, db):
        article = _seed_article(db, status=APPROVED)
        client = _FakeBloggerClient()

        result = await recover_stuck_publishing(db, article, client)

        assert result.status == APPROVED  # unchanged


# --- Migration tests ---------------------------------------------------------


class TestMigration:
    """Additive columns are created correctly on existing tables."""

    def test_article_has_blogger_columns(self, db):
        article = _seed_article(db)
        # These should be accessible without error
        assert hasattr(article, "blogger_post_id")
        assert hasattr(article, "blogger_post_url")
        assert hasattr(article, "blogger_published_at")
        assert hasattr(article, "blogger_status")
        assert article.blogger_post_id is None
        assert article.blogger_post_url is None
        assert article.blogger_published_at is None
        assert article.blogger_status is None

    def test_publish_job_has_blogger_post_id(self, db):
        from datetime import datetime, timezone
        article = _seed_article(db)
        job = PublishJob(article_id=article.id, run_at=datetime.now(timezone.utc))
        db.add(job)
        db.commit()
        assert hasattr(job, "blogger_post_id")
        assert job.blogger_post_id is None

    def test_migration_idempotent(self):
        """Running migration twice does not fail."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        apply_publish_column_migrations(engine)
        # Run again — should not raise
        apply_publish_column_migrations(engine)
