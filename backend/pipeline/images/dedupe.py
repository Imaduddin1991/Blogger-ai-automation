"""Deterministic image deduplication (Phase 4C).

Deduplication is URL/source-based only (no downloads, no content hashes).
Within a search and across providers, candidates collapse onto a canonical
image URL plus a near-identical-title key (per provider, so two different
"Cat" photos from different providers stay distinct). Normalization is
conservative: only the scheme/host casing, default port, trailing slash,
fragment, and query-param ordering are canonicalized — the URL path (the real
asset identity) is never altered, so distinct assets cannot be merged.

Cross-article reuse is informational only (the approved plan does not
hard-block it): humans may intentionally re-select an image used elsewhere.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse

from sqlalchemy import select

from db.models import Article, Image
from pipeline.images.providers.base import ImageResult

_TITLE_RE = re.compile(r"[^a-z0-9]+")
_TRAILING_SLASH_RE = re.compile(r"/+$")


def canonical_image_url(url: str) -> str:
    """Conservative canonical key for an image URL.

    Lowercases the scheme and host, drops the default port, strips the
    trailing slash and fragment, and sorts query params. The path and query
    values are preserved exactly.
    """
    candidate = (url or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return candidate.rstrip("/")
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not scheme or not host:
        return candidate.rstrip("/")
    try:
        port = parsed.port
    except ValueError:
        port = None
    default = 443 if scheme == "https" else (80 if scheme == "http" else None)
    if port is not None and port == default:
        port = None
    netloc = host if port is None else f"{host}:{port}"
    path = _TRAILING_SLASH_RE.sub("", parsed.path or "")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True))) if parsed.query else ""
    rebuilt = f"{scheme}://{netloc}{path}"
    return f"{rebuilt}?{query}" if query else rebuilt


def _normalize_title(title: str) -> str:
    """Case/punctuation-normalized title used for near-duplicate collapse."""
    return _TITLE_RE.sub(" ", (title or "").lower()).strip()


def dedupe_candidates(results: list[ImageResult]) -> list[ImageResult]:
    """Collapse duplicate candidates, keeping the most relevant first.

    Dedupe keys: canonical image URL (across providers) and normalized title
    within the same provider. Candidates without a parseable URL are kept
    as-is (they still must pass validation before persisting).
    """
    ordered = sorted(results, key=lambda r: (r.relevance, r.dedupe_key()), reverse=True)
    by_url: set[str] = set()
    by_title: set[tuple[str, str]] = set()
    kept: list[ImageResult] = []
    for result in ordered:
        url_key = canonical_image_url(result.image_url)
        if url_key and url_key in by_url:
            continue
        title_key = (result.provider.lower(), _normalize_title(result.title))
        if title_key[1] and title_key in by_title:
            continue
        if url_key:
            by_url.add(url_key)
        by_title.add(title_key)
        kept.append(result)
    return kept


def find_image_usage(db, image_url: str, *, exclude_article_id: int | None = None) -> list[dict]:
    """Which articles already use this image (informational, never blocking).

    Returns rows like {"article_id", "article_title", "status"} for images on
    other articles whose canonical URL matches. `exclude_article_id` lets a
    caller ignore the article currently being edited.
    """
    url_key = canonical_image_url(image_url)
    if not url_key:
        return []
    stmt = select(Image).where(Image.article_id.isnot(None))
    if exclude_article_id is not None:
        stmt = stmt.where(Image.article_id != exclude_article_id)
    used: list[dict] = []
    for image in db.scalars(stmt):
        if canonical_image_url(image.url) != url_key:
            continue
        article = db.get(Article, image.article_id)
        used.append(
            {
                "article_id": image.article_id,
                "article_title": article.title if article else None,
                "status": image.status,
            }
        )
    return used
