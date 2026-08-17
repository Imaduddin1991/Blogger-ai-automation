"""Content builder and publishing service for Blogger (Phases 5C + 5D).

Converts article markdown body to Blogger-safe HTML, embeds images with
attribution, appends source references, and sanitizes the output. The
publishing service orchestrates state transitions, API calls, and audit
logging.

The markdown renderer is a direct Python port of frontend/src/lib/markdown.ts
to keep frontend preview and published output consistent. No external markdown
library is needed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as _html_escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Article, BlogConnection, PublishJob, PublishLog, Research
from pipeline.state import (
    APPROVED,
    PUBLISHED,
    PUBLISH_FAILED,
    PUBLISHING,
    transition,
)
from services.blogger_client import (
    BloggerAPIError,
    BloggerAuthError,
    BloggerClient,
    BloggerError,
    BloggerTimeoutError,
)

logger = logging.getLogger(__name__)


# --- HTML escaping and URL safety ------------------------------------------


def escape_html(value: str) -> str:
    """Escape HTML special characters. Port of frontend escapeHtml."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# Dangerous URL schemes that must never appear in href/src attributes.
_DANGEROUS_SCHEMES = re.compile(
    r"^\s*(javascript|data|vbscript|file|blob|ftp|telnet|ssh):",
    re.IGNORECASE,
)


def safe_url(value: str | None) -> str | None:
    """Return the URL if safe (http/https/mailto or scheme-less), else None.

    Port of frontend safeUrl with additional dangerous-scheme rejection.
    """
    if not value:
        return None
    trimmed = value.strip()
    if _DANGEROUS_SCHEMES.match(trimmed):
        return None
    if re.match(r"^https?://", trimmed, re.IGNORECASE):
        return trimmed
    if re.match(r"^mailto:", trimmed, re.IGNORECASE):
        return trimmed
    if ":" not in trimmed:
        return trimmed
    return None


# --- Inline markdown --------------------------------------------------------


def _inline_markdown(value: str) -> str:
    """Convert inline markdown (bold, italic, code, links) to HTML.

    Port of frontend inlineMarkdown.
    """
    # Bold: **text**
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    # Italic: *text*
    value = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", value)
    # Inline code: `text`
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    # Links: [text](url)
    value = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: _render_link(m.group(1), m.group(2)),
        value,
    )
    return value


def _render_link(text: str, url: str) -> str:
    """Render a markdown link, sanitizing the URL."""
    safe = safe_url(url)
    if safe:
        return f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{text}</a>'
    # Dangerous URL: render as plain text with the URL in parentheses
    return f"{text} ({url})"


# --- Block-level markdown ---------------------------------------------------


def markdown_to_html(markdown: str) -> str:
    """Convert markdown text to HTML. Port of frontend renderMarkdown.

    Handles: headings, paragraphs, unordered lists, fenced code blocks,
    blockquotes, and inline formatting. All raw HTML in the input is escaped.
    """
    if not markdown:
        return ""

    lines = markdown.replace("\r\n", "\n").split("\n")
    html: list[str] = []
    para: list[str] = []
    in_list = False
    in_code = False

    def flush_para() -> None:
        if para:
            html.append(f"<p>{_inline_markdown(escape_html(' '.join(para)))}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in lines:
        # Fenced code block toggle
        if raw.strip().startswith("```"):
            flush_para()
            close_list()
            if in_code:
                html.append("</code></pre>")
                in_code = False
            else:
                html.append("<pre><code>")
                in_code = True
            continue

        # Inside code block: escape and output verbatim
        if in_code:
            html.append(escape_html(raw))
            continue

        trimmed = raw.strip()

        # Blank line: flush paragraph and close list
        if trimmed == "":
            flush_para()
            close_list()
            continue

        # Headings: # ... ######
        heading = re.match(r"^(#{1,6})\s+(.*)$", trimmed)
        if heading:
            flush_para()
            close_list()
            level = len(heading.group(1))
            text = _inline_markdown(escape_html(heading.group(2)))
            html.append(f"<h{level}>{text}</h{level}>")
            continue

        # Unordered list items: - item or * item
        list_item = re.match(r"^[-*]\s+(.*)$", trimmed)
        if list_item:
            flush_para()
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(escape_html(list_item.group(1)))}</li>")
            continue

        # Blockquotes: > text
        if trimmed.startswith(">"):
            flush_para()
            close_list()
            content = re.sub(r"^>\s?", "", trimmed)
            html.append(f"<blockquote>{_inline_markdown(escape_html(content))}</blockquote>")
            continue

        # Regular paragraph text
        para.append(raw)

    flush_para()
    close_list()
    if in_code:
        html.append("</code></pre>")

    return "\n".join(html)


# --- Content builder --------------------------------------------------------


@dataclass
class ImageRef:
    """Simplified image reference for content building."""

    url: str
    alt: str = ""
    caption: str = ""
    attribution: str = ""
    license: str = ""


@dataclass
class SourceRef:
    """Simplified source reference for content building."""

    title: str
    url: str
    provider: str = ""
    snippet: str = ""


def _render_image(img: ImageRef) -> str:
    """Render a single image as Blogger-safe HTML."""
    src = safe_url(img.url)
    if not src:
        return ""
    alt = escape_html(img.alt)
    parts = [f'<img src="{src}" alt="{alt}" style="max-width:100%;height:auto;" />']
    if img.caption:
        parts.append(f"<p><em>{escape_html(img.caption)}</em></p>")
    if img.attribution:
        parts.append(f"<p><small>{escape_html(img.attribution)}</small></p>")
    return "\n".join(parts)


def _render_sources(sources: list[SourceRef]) -> str:
    """Render a 'Sources' section at the end of the article."""
    if not sources:
        return ""
    items = []
    for s in sources:
        url = safe_url(s.url)
        title = escape_html(s.title)
        if url:
            items.append(f'<li><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></li>')
        else:
            items.append(f"<li>{title}</li>")
    return (
        "<h2>Sources</h2>\n<ul>\n"
        + "\n".join(items)
        + "\n</ul>"
    )


def build_post_html(
    title: str,
    body: str,
    *,
    images: list[ImageRef] | None = None,
    sources: list[SourceRef] | None = None,
) -> str:
    """Build the full HTML content for a Blogger post.

    Combines the article title, converted markdown body, embedded images
    (sorted by position), and a sources section. Output is Blogger-safe HTML.

    This does NOT wrap in <html>/<head>/<body> — Blogger expects just the
    post content fragment.
    """
    parts: list[str] = []

    # Article title as H1
    if title:
        parts.append(f"<h1>{escape_html(title)}</h1>")

    # Main body: markdown -> HTML
    body_html = markdown_to_html(body)
    if body_html:
        parts.append(body_html)

    # Images (sorted by insertion order / position)
    if images:
        for img in images:
            rendered = _render_image(img)
            if rendered:
                parts.append(rendered)

    # Sources section
    sources_html = _render_sources(sources or [])
    if sources_html:
        parts.append(sources_html)

    return "\n\n".join(parts)


# --- HTML sanitization ------------------------------------------------------


# Tags and attributes we allow in the final output. Everything else is stripped.
_ALLOWED_TAGS = frozenset(
    {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr",
        "strong", "em", "b", "i", "u",
        "a", "img",
        "ul", "ol", "li",
        "blockquote",
        "pre", "code",
        "table", "thead", "tbody", "tr", "th", "td",
        "small", "figure", "figcaption",
        "div", "span",
    }
)

_ALLOWED_ATTRS = {
    "a": {"href", "target", "rel", "title"},
    "img": {"src", "alt", "width", "height", "style", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

# Attribute values that could execute code
_DANGEROUS_ATTR_VALUES = re.compile(
    r"(javascript|data|vbscript)\s*:", re.IGNORECASE
)

_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>")
_ATTR_RE = re.compile(r'(\w[\w-]*)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+)))?')


def sanitize_html(html: str) -> str:
    """Final sanitization pass for Blogger-safe HTML.

    Strips disallowed tags, removes dangerous attributes (onclick, style with
    expressions, etc.), and ensures all URLs are safe.

    This is a lightweight sanitizer for our own generated content — not a
    general-purpose XSS filter. The input is already escaped markdown output.
    """
    if not html:
        return ""

    def _replace_tag(m: re.Match) -> str:
        is_close = m.group(1) == "/"
        tag = m.group(2).lower()
        attrs_str = m.group(3)

        if tag not in _ALLOWED_TAGS:
            return ""

        if is_close:
            return f"</{tag}>"

        # Parse attributes
        attrs: dict[str, str] = {}
        for attr_match in _ATTR_RE.finditer(attrs_str):
            name = attr_match.group(1).lower()
            value = attr_match.group(2) or attr_match.group(3) or attr_match.group(4) or ""

            # Check if this attribute is allowed for this tag
            allowed = _ALLOWED_ATTRS.get(tag, set())
            if name not in allowed:
                continue

            # Check for dangerous values
            if _DANGEROUS_ATTR_VALUES.search(value):
                continue

            # Sanitize URL attributes
            if name in ("href", "src"):
                safe = safe_url(value)
                if safe is None:
                    continue
                value = safe

            # Escape attribute values
            value = value.replace("&", "&amp;").replace('"', "&quot;")
            attrs[name] = value

        # Build tag string
        attr_str = "".join(f' {k}="{v}"' for k, v in attrs.items())
        return f"<{tag}{attr_str}>"

    result = _TAG_RE.sub(_replace_tag, html)
    # Also strip HTML comments
    result = re.sub(r"<!--.*?-->", "", result, flags=re.DOTALL)
    return result


# --- Publishing service (Phase 5D) ------------------------------------------


def _build_content_payload(article: Article) -> tuple[str, str]:
    """Build the post title and HTML content from an Article row.

    Returns (title, html) ready for the Blogger API. Images are sourced from
    the article's selected images; sources from the linked research.
    """
    title = article.seo_title or article.title or ""

    # Build image refs from selected images
    images = []
    for img in sorted(article.images, key=lambda i: i.position):
        if img.status == "selected":
            images.append(
                ImageRef(
                    url=img.url,
                    alt=img.alt or "",
                    caption=img.caption or "",
                    attribution=img.attribution or "",
                    license=img.license or "",
                )
            )

    # Build source refs from linked research
    sources = []
    if article.idea_id is not None:
        # Avoid lazy-load issues: query directly
        research = None
        # We don't have a session here, so we use the article's relationships.
        # The caller must ensure sources are loaded if needed.
        # Fallback: sources come from the article's relationship if populated.
        pass
    # Sources are passed in from the caller when available.
    # For now, build with images only; caller can enrich sources.

    body_html = build_post_html(title, article.body or "", images=images)
    return title, sanitize_html(body_html)


def _build_content_payload_full(
    article: Article,
    sources: list[SourceRef] | None = None,
) -> tuple[str, str]:
    """Build post title and sanitized HTML with sources included.

    Used by the publishing service which has access to the DB session
    to load sources from the research.
    """
    title = article.seo_title or article.title or ""

    images = []
    for img in sorted(article.images, key=lambda i: i.position):
        if img.status == "selected":
            images.append(
                ImageRef(
                    url=img.url,
                    alt=img.alt or "",
                    caption=img.caption or "",
                    attribution=img.attribution or "",
                    license=img.license or "",
                )
            )

    body_html = build_post_html(title, article.body or "", images=images, sources=sources)
    return title, sanitize_html(body_html)


def _load_sources_from_article(db: Session, article: Article) -> list[SourceRef]:
    """Load research sources linked to the article via its idea."""
    if article.idea_id is None:
        return []
    research = db.scalars(
        select(Research)
        .where(Research.idea_id == article.idea_id)
        .order_by(Research.id.desc())
        .limit(1)
    ).first()
    if research is None:
        return []
    return [
        SourceRef(
            title=s.title,
            url=s.url,
            provider=s.provider,
            snippet=s.snippet or "",
        )
        for s in research.sources
    ]


def _log_publish_event(
    db: Session,
    article_id: int,
    action: str,
    result: str,
    details: dict | None = None,
) -> None:
    """Append an entry to the publish audit log."""
    log = PublishLog(
        article_id=article_id,
        action=action,
        result=result,
        details=details,
    )
    db.add(log)
    db.commit()


def _ensure_publish_job(db: Session, article_id: int) -> PublishJob | None:
    """Return the active or most recent PublishJob for this article, or None."""
    return db.scalars(
        select(PublishJob)
        .where(PublishJob.article_id == article_id)
        .order_by(PublishJob.id.desc())
        .limit(1)
    ).first()


class PublishError(RuntimeError):
    """Raised when publishing fails with a recoverable or terminal error."""


async def publish_to_blogger(
    db: Session,
    article: Article,
    connection: BlogConnection,
    client: BloggerClient,
    *,
    as_draft: bool = False,
) -> Article:
    """Publish an article to Blogger.

    Orchestrates the full publish flow:
    1. Gate: article must be APPROVED.
    2. Transition APPROVED -> PUBLISHING.
    3. Build HTML from article body + images + sources.
    4. Insert or update (idempotent) on Blogger.
    5. Persist blogger_post_id, blogger_post_url, blogger_status.
    6. Transition PUBLISHING -> PUBLISHED.
    7. Log to PublishLog.

    On failure: transitions to PUBLISH_FAILED, records error, logs to PublishLog.

    This function does NOT submit to the serial runner — the caller (5E API
    endpoints or article_runner) handles job submission.
    """
    # --- Pre-flight gate ---
    db.refresh(article)
    if article.status != APPROVED:
        raise PublishError(
            f"Article {article.id} is '{article.status}', must be '{APPROVED}' to publish"
        )
    if not connection.blog_id:
        raise PublishError("No blog_id on BlogConnection — reconnect Blogger first")

    # --- Create PublishJob ---
    job = PublishJob(
        article_id=article.id,
        run_at=datetime.now(timezone.utc),
        status="running",
        retry_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # --- Transition to PUBLISHING ---
    article.status = transition(article.status, PUBLISHING)
    db.commit()

    # --- Build content ---
    try:
        sources = _load_sources_from_article(db, article)
        title, html_content = _build_content_payload_full(article, sources=sources)
    except Exception as exc:
        _fail_publish(db, article, job, f"Content build failed: {type(exc).__name__}: {exc}")
        raise PublishError(f"Content build failed: {exc}") from exc

    # --- Call Blogger API ---
    try:
        if article.blogger_post_id:
            # Idempotent update: article was previously published
            post = await client.update_post(
                connection.blog_id,
                article.blogger_post_id,
                title=title,
                content=html_content,
                labels=article.labels or None,
            )
            action = "update"
        else:
            # First publish
            post = await client.insert_post(
                connection.blog_id,
                title,
                html_content,
                labels=article.labels or None,
                is_draft=as_draft,
            )
            action = "insert"
    except BloggerAuthError as exc:
        _fail_publish(db, article, job, f"Blogger auth error: {type(exc).__name__}")
        raise PublishError(f"Blogger auth error: {exc}") from exc
    except BloggerTimeoutError as exc:
        _fail_publish(db, article, job, f"Blogger API timeout: {type(exc).__name__}")
        raise PublishError(f"Blogger API timeout: {exc}") from exc
    except BloggerAPIError as exc:
        error_msg = str(exc)
        # Sanitize error messages: strip any token-like strings
        error_msg = _sanitize_error(error_msg)
        _fail_publish(db, article, job, f"Blogger API error: {error_msg}")
        raise PublishError(f"Blogger API error: {exc}") from exc
    except BloggerError as exc:
        _fail_publish(db, article, job, f"Blogger error: {type(exc).__name__}")
        raise PublishError(f"Blogger error: {exc}") from exc
    except Exception as exc:
        _fail_publish(db, article, job, f"Unexpected error: {type(exc).__name__}")
        raise PublishError(f"Unexpected error: {exc}") from exc

    # --- Success: persist blogger metadata ---
    db.refresh(article)
    article.blogger_post_id = post.id
    article.blogger_post_url = post.url
    article.blogger_published_at = datetime.now(timezone.utc)
    article.blogger_status = "draft" if as_draft else "live"

    article.status = transition(article.status, PUBLISHED)

    # Update job
    job.status = "completed"
    job.blogger_post_id = post.id
    job.published_at = datetime.now(timezone.utc)
    db.commit()

    _log_publish_event(
        db,
        article.id,
        action=action,
        result="success",
        details={
            "post_id": post.id,
            "post_url": post.url,
            "as_draft": as_draft,
        },
    )
    logger.info(
        "Published article %s (%s post %s)",
        article.id,
        action,
        post.id,
    )
    return article


def _fail_publish(db: Session, article: Article, job: PublishJob, error: str) -> None:
    """Transition to PUBLISH_FAILED, record error, log."""
    try:
        db.refresh(article)
        if article.status == PUBLISHING:
            article.status = transition(article.status, PUBLISH_FAILED)
    except Exception:
        db.rollback()
        # If transition fails, force-set for safety (row is in PUBLISHING limbo)
        try:
            db.refresh(article)
            article.status = PUBLISH_FAILED
        except Exception:
            pass

    job.status = "failed"
    job.error = _sanitize_error(error)
    try:
        db.commit()
    except Exception:
        db.rollback()

    _log_publish_event(
        db,
        article.id,
        action="publish",
        result="failure",
        details={"error": _sanitize_error(error)},
    )


def _sanitize_error(message: str) -> str:
    """Strip any token-like substrings from error messages.

    Ensures OAuth tokens, access tokens, or other secrets never appear in
    persisted error messages or logs.
    """
    # Remove Fernet-like token strings: base64 segment(s) separated by dots
    sanitized = re.sub(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", "[REDACTED]", message)
    # Remove standalone long base64 strings (potential access tokens, 30+ chars)
    sanitized = re.sub(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])", "[REDACTED]", sanitized)
    # Remove any Bearer tokens
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", sanitized)
    return sanitized


async def recover_stuck_publishing(
    db: Session, article: Article, client: BloggerClient
) -> Article:
    """Recover an article stuck in PUBLISHING state after a process restart.

    Checks if a Blogger post already exists for this article. If found,
    transitions to PUBLISHED and records the post metadata. If not found,
    transitions to PUBLISH_FAILED so the user can retry.

    This is the "lazy-resume" described in the plan: on next GET for the
    article, if status is PUBLISHING and no job is running, call this.
    """
    db.refresh(article)
    if article.status != PUBLISHING:
        return article

    if article.blogger_post_id and article.blog_id:
        # We have a post ID — verify it exists on Blogger
        conn = db.scalars(
            select(BlogConnection).where(BlogConnection.id == article.blog_id)
        ).first()
        if conn and conn.token_encrypted and conn.blog_id:
            from app.config import get_settings
            from services.blogger_client import TokenCryptor

            settings = get_settings()
            try:
                cryptor = TokenCryptor(settings.encryption_key)
                token = cryptor.decrypt_token(conn.token_encrypted)
                client.token = token
                post = await client.get_post(conn.blog_id, article.blogger_post_id)
                # Post exists — mark as published
                article.status = transition(article.status, PUBLISHED)
                article.blogger_post_url = post.url
                article.blogger_published_at = article.blogger_published_at or datetime.now(timezone.utc)
                article.blogger_status = "draft" if post.is_draft else "live"
                db.commit()
                _log_publish_event(
                    db, article.id, action="recover", result="found_post",
                    details={"post_id": post.id},
                )
                return article
            except (BloggerError, BloggerAuthError):
                pass  # Can't verify — fall through to PUBLISH_FAILED

    # Cannot recover — mark as failed so user can retry
    try:
        article.status = transition(article.status, PUBLISH_FAILED)
    except Exception:
        article.status = PUBLISH_FAILED
    db.commit()
    _log_publish_event(
        db, article.id, action="recover", result="no_post_found",
    )
    return article
