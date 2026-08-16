"""Provider-independent image validation / rejection rules (Phase 4C).

Every candidate must pass these deterministic rules before it can be
persisted or selected, regardless of provider. The rules encode the approved
Phase 4 licensing policy (allowlist only; reject unknown/ambiguous/NC/ND),
https-only URLs, a raster-only MIME allowlist (blocks SVG/scripts), and
oversized-file / invalid-dimension guards. Metadata is untrusted: nothing here
renders it, and the future downloader still owns host-allowlist and redirect
validation — this layer never fetches a remote URL.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pipeline.images.providers.base import (
    ATTRIBUTION_REQUIRED_LICENSES,
    ImageResult,
    normalize_license,
    verify_license,
)

# Raster formats the MVP accepts. SVG and anything else is rejected: the app
# never sanitizes or renders SVG, so it is excluded by MIME type up front.
ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)

# Oversized guards from the approved plan (no downloads in this phase).
MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_DIMENSION = 10000  # px

_SVG_EXTENSIONS = (".svg", ".svgz")
_FORBIDDEN_SCHEMES = ("javascript", "data", "file")


def _scheme_problem(value: str) -> str | None:
    """Return a problem reason for an unsafe URL, or None when https is fine."""
    candidate = (value or "").strip()
    if not candidate:
        return "url is missing"
    if any(ch.isspace() or ord(ch) < 32 for ch in candidate):
        return "url contains whitespace or control characters"
    parsed = urlparse(candidate)
    scheme = (parsed.scheme or "").lower()
    if scheme in _FORBIDDEN_SCHEMES:
        return f"url uses forbidden scheme: {scheme}"
    if scheme != "https":
        return "url must use the https scheme"
    if not parsed.hostname:
        return "url has no host"
    return None


def _positive_dimension(value: object) -> bool:
    """True when a dimension is a real positive integer (bool excluded)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_image_metadata(result: ImageResult) -> list[str]:
    """Return rejection reasons for a candidate, or [] when it is usable.

    Conservative by design: an unknown license, missing MIME metadata, or a
    dimension we cannot prove valid all reject — a candidate must be clearly
    usable to pass.
    """
    problems: list[str] = []

    verdict = verify_license(result.license, author=result.author)
    if not verdict.allowed:
        problems.append(verdict.reason)
    elif normalize_license(result.license) in ATTRIBUTION_REQUIRED_LICENSES and not result.attribution_required:
        problems.append("attribution_required is false for a license that requires attribution")

    for field in ("image_url", "page_url"):
        value = (getattr(result, field) or "").strip()
        problem = _scheme_problem(value)
        if problem:
            problems.append(f"{field} {problem}")

    thumb_url = (result.thumb_url or "").strip()
    if thumb_url:
        problem = _scheme_problem(thumb_url)
        if problem:
            problems.append(f"thumb_url {problem}")

    license_url = (result.license_url or "").strip()
    if license_url:
        problem = _scheme_problem(license_url)
        if problem:
            problems.append(f"license_url {problem}")

    mime = (result.mime or "").strip().lower()
    if mime not in ALLOWED_IMAGE_MIMES:
        problems.append(f"mime {mime or 'missing'} is not an allowed raster type")
    if mime == "image/svg+xml" or (result.image_url or "").lower().endswith(_SVG_EXTENSIONS):
        problems.append("svg images are not supported")

    if result.file_size is not None and result.file_size > MAX_IMAGE_FILE_SIZE:
        problems.append(f"file size {result.file_size} exceeds {MAX_IMAGE_FILE_SIZE} bytes")

    for field in ("width", "height"):
        value = getattr(result, field)
        if value is not None and not _positive_dimension(value):
            problems.append(f"{field} must be a positive integer")
        elif value is not None and value > MAX_IMAGE_DIMENSION:
            problems.append(f"{field} {value} exceeds {MAX_IMAGE_DIMENSION} px")

    return problems
