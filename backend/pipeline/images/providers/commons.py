"""Wikimedia Commons image provider (Phase 4B).

Commons `api.php` `generator=search` + `prop=imageinfo` with `extmetadata`.
Keyless and bounded: a single page of results, never followed continuation
tokens, so responses stay small. Each candidate is license-checked against
the Phase 4A policy (CC0 / Public Domain / CC BY / CC BY-SA only) and dropped
when it cannot be confidently mapped. Malformed candidates are skipped, never
allowed to crash the search. The policy is never weakened here.
"""

from __future__ import annotations

import html
import re

import httpx

from pipeline.images.providers.base import (
    ATTRIBUTION_REQUIRED_LICENSES,
    ImageProvider,
    ImageProviderError,
    ImageResult,
    normalize_license,
    verify_license,
)
from pipeline.images.providers.registry import register
from pipeline.images.relevance import compute_image_relevance
from pipeline.research.providers.base import USER_AGENT

_API = "https://commons.wikimedia.org/w/api.php"
_MAX_LIMIT = 50  # Commons caps gsrlimit at 50 for non-bot accounts
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

_TAG_RE = re.compile(r"<[^>]+>")
_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|tiff?|bmp|svgz?)$", re.IGNORECASE)


def _text(value: str | None) -> str:
    """Extract plain text from a Commons metadata value (may contain HTML).

    Text is extracted, never rendered: tags are stripped and entities
    unescaped so no remote content is ever trusted or executed.
    """
    if not value:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html.unescape(value))).strip()


def _meta_value(meta: dict, key: str) -> str | None:
    entry = meta.get(key)
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    return value if isinstance(value, str) else None


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _display_title(title: str) -> str:
    """Human title from a Commons file page title (drop prefix/extension)."""
    base = title[5:] if title.lower().startswith("file:") else title
    base = _EXT_RE.sub("", base.replace("_", " "))
    return base.strip()


async def _fetch(params: dict) -> dict:
    """One bounded Commons API call. Raises ImageProviderError on failure."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _API, params=params, timeout=10.0, follow_redirects=True, headers=_HEADERS
            )
    except httpx.HTTPError as exc:
        raise ImageProviderError(f"network error: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise ImageProviderError(f"HTTP {resp.status_code} for {_API}")
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise ImageProviderError("non-JSON response") from exc


@register
class CommonsProvider(ImageProvider):
    name = "commons"
    display_name = "Wikimedia Commons"

    async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
        try:
            bounded = min(max(int(limit), 1), _MAX_LIMIT)
        except (TypeError, ValueError):
            bounded = 8
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap|filetype:drawing",
            "gsrnamespace": "6",
            "gsrlimit": str(bounded),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "400",
            "format": "json",
            "formatversion": "2",
        }
        data = await _fetch(params)
        if data.get("error"):
            detail = (data["error"].get("info") or str(data["error"])).strip()
            raise ImageProviderError(f"Commons API error: {detail}")
        resp_query = data.get("query") or {}
        pages = resp_query.get("pages") or []
        if not isinstance(pages, list):
            raise ImageProviderError("unexpected API response structure")
        pages = [p for p in pages if isinstance(p, dict)]
        pages = sorted(pages, key=lambda p: (p.get("index") is None, p.get("index") or 0))

        results: list[ImageResult] = []
        for page in pages:
            try:
                result = self._parse_page(query_text=query, page=page)
            except Exception:
                continue  # malformed candidate: skip, never crash the search
            if result is not None:
                results.append(result)
        return results

    def _parse_page(self, query_text: str, page: dict) -> ImageResult | None:
        title = (page.get("title") or "").strip()
        if not title:
            return None
        imageinfo_list = page.get("imageinfo") or []
        if not imageinfo_list or not isinstance(imageinfo_list[0], dict):
            return None
        info = imageinfo_list[0]

        image_url = (info.get("url") or "").strip()
        page_url = (info.get("descriptionurl") or "").strip()
        if not image_url or not page_url:
            return None

        meta = info.get("extmetadata") or {}
        license_name = _text(_meta_value(meta, "LicenseShortName"))
        author = _text(_meta_value(meta, "Artist"))
        verdict = verify_license(license_name, author=author)
        if not verdict.allowed:
            return None

        display_title = _text(_meta_value(meta, "ObjectName")) or _display_title(title)
        description = _text(_meta_value(meta, "ImageDescription")) or None
        license_url = (_meta_value(meta, "LicenseUrl") or "").strip()
        license_url = license_url if license_url.startswith("https://") else None
        usage_notes = _text(_meta_value(meta, "UsageTerms")) or None
        canonical = normalize_license(license_name)

        result = ImageResult(
            provider=self.name,
            image_url=image_url,
            page_url=page_url,
            title=display_title,
            description=description,
            thumb_url=(info.get("thumburl") or "").strip() or None,
            author=author or None,
            license=license_name or None,
            license_url=license_url,
            attribution_required=canonical in ATTRIBUTION_REQUIRED_LICENSES,
            usage_notes=usage_notes,
            mime=(info.get("mime") or "").strip() or None,
            width=_positive_int(info.get("width")),
            height=_positive_int(info.get("height")),
            file_size=_positive_int(info.get("size")),
            relevance=compute_image_relevance(query_text, display_title, description),
        )
        if result.validate():
            return None
        return result
