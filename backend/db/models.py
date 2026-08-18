"""Core data entities.

Phase 1 creates the full schema so the data layer is stable; only
Setting and Idea are wired into APIs/UI yet. Later phases add rows for
the pipeline stages without schema churn.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Setting(Base, TimestampMixin):
    """Key/value configuration stored in the DB (survives restarts, editable in UI)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class BlogConnection(Base, TimestampMixin):
    """A connected Blogger blog with its OAuth token material (encrypted at rest)."""

    __tablename__ = "blog_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    blog_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    blog_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Idea(Base, TimestampMixin):
    """The starting input: a blog topic the user wants written."""

    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    research: Mapped[list["Research"]] = relationship(back_populates="idea", cascade="all, delete-orphan")
    articles: Mapped[list["Article"]] = relationship(back_populates="idea", cascade="all, delete-orphan")


class Research(Base, TimestampMixin):
    """Research snapshot for an idea, with a cache key for the topic."""

    __tablename__ = "research"
    __table_args__ = (UniqueConstraint("topic_key", name="uq_research_topic_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("ideas.id"), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    topic_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    providers_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_errors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")

    idea: Mapped[Idea | None] = relationship(back_populates="research")
    sources: Mapped[list["Source"]] = relationship(back_populates="research", cascade="all, delete-orphan")


class Source(Base):
    """A normalized source returned by a research provider."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_id: Mapped[int | None] = mapped_column(ForeignKey("research.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    license: Mapped[str | None] = mapped_column(String(100), nullable=True)

    research: Mapped[Research | None] = relationship(back_populates="sources")


class Article(Base, TimestampMixin):
    """The generated article and its lifecycle state."""

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("idea_id", name="uq_articles_idea_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("ideas.id"), nullable=True)
    blog_id: Mapped[int | None] = mapped_column(ForeignKey("blog_connections.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    generation_errors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Phase 5D: Blogger publishing metadata
    blogger_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    blogger_post_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blogger_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    blogger_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    idea: Mapped[Idea | None] = relationship(back_populates="articles")
    images: Mapped[list["Image"]] = relationship(back_populates="article", cascade="all, delete-orphan")
    check_results: Mapped[list["CheckResult"]] = relationship(back_populates="article", cascade="all, delete-orphan")


class Image(Base, TimestampMixin):
    """An image attached to an article (from a free source), with attribution.

    Phase 4C extends the Phase 1 model additively with the metadata the image
    stage needs (status lifecycle, source page, license details, size guards,
    relevance, retrieval time). Existing columns are reused: `url` is the
    canonical image URL, `caption` holds the title, `alt` the description,
    `attribution` the rendered credit line, `license` the raw license string.
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    alt: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(100), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Phase 4C additions (additive; safe on existing rows).
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumb_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(50), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    article: Mapped[Article | None] = relationship(back_populates="images")


class CheckResult(Base, TimestampMixin):
    """One row per automated check (SEO / quality / policy / repetition)."""

    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), nullable=True)
    check_type: Mapped[str] = mapped_column(String(50), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    article: Mapped[Article | None] = relationship(back_populates="check_results")


class PublishJob(Base, TimestampMixin):
    """A queued publish: immediate or scheduled (APScheduler consumes due jobs)."""

    __tablename__ = "publish_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Phase 5D: Blogger post ID for idempotent updates
    blogger_post_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class PublishLog(Base):
    """Audit trail for every external publish action."""

    __tablename__ = "publish_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str] = mapped_column(String(30), default="unknown")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
