"""ImageProvider contract, normalized image record, and license policy.

The core image pipeline will depend only on this interface, never on a
concrete provider. To add a free provider later: implement ImageProvider,
register it, done. The pipeline, article generation, and data model do not
change.

Provider-supplied metadata is untrusted data. Before any candidate can be
persisted or selected it must pass the provider-independent license policy
(verify_license) and the structural checks on ImageResult.validate(); MIME
verification and download handling arrive with a later phase.
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass
from datetime import datetime

# --- License policy (provider-independent, MVP) --------------------------
#
# Accepted licenses only (AdSense-safe / commercial-compatible). Everything
# else is rejected: unknown strings, ambiguous spellings, and licenses whose
# terms cannot be verified from the metadata alone.
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {"cc0", "public domain", "cc by", "cc by-sa"}
)

# License families that are always rejected regardless of spelling. Caught on
# the normalized text before canonicalization so the reason names the real
# problem. Variants include camelCase forms ("NoCommercial", "NoDerivs") that
# must be split before matching.
DENIED_LICENSE_MARKERS: tuple[str, ...] = (
    "nc", "nd", "noncommercial", "non-commercial", "commercial",
    "noderivs", "noderivatives", "no derivs", "no derivatives",
    "fair use", "permission", "copyrighted", "non-free",
)

# These licenses legally require a credit line, so the author must be present
# for the required attribution to be renderable.
ATTRIBUTION_REQUIRED_LICENSES: frozenset[str] = frozenset({"cc by", "cc by-sa"})

_MIN_RELEVANCE = 0.2  # same relevance floor as the research providers


def _normalize_text(name: str) -> str:
    """Normalize a raw license string for matching: lowercase, single spaces,
    hyphens/underscores to spaces, and camelCase split so "NoCommercial"
    becomes "no commercial" (a word-boundary match).
    """
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    text = text.lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_license(name: str | None) -> str | None:
    """Map a raw license string to a canonical key, or None when unrecognized.

    Handles the common spellings and version suffixes a provider (e.g.
    Wikimedia Commons `extmetadata`) emits: "CC BY-SA 4.0", "cc-by-sa-4.0",
    "Creative Commons Attribution-ShareAlike 4.0 International", "CC0",
    "Public domain". Returns one of the ALLOWED_LICENSES keys or None.
    """
    if not name:
        return None
    text = _normalize_text(name)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", " ", text)  # drop version numbers
    text = re.sub(r"\s+", " ", text).strip()
    if re.search(r"\bcc\s*0\b", text) or "zero" in text:
        return "cc0"
    if "public domain" in text or re.search(r"\bpd\b", text):
        return "public domain"
    if re.search(r"\bcc by sa\b", text) or "sharealike" in text or "share alike" in text:
        return "cc by-sa"
    if "by" in text or "attribution" in text:
        return "cc by"
    return None


@dataclass(frozen=True)
class LicenseVerdict:
    """Result of the license policy check for one candidate."""

    allowed: bool
    reason: str = ""


def verify_license(name: str | None, *, author: str | None = None) -> LicenseVerdict:
    """Accept/reject a candidate license under the MVP policy.

    Unknown or ambiguous licensing is rejected, never silently accepted.
    For attribution licenses (CC BY / CC BY-SA) the author must be present so
    the required credit can be rendered.
    """
    if not name:
        return LicenseVerdict(False, "license metadata missing")
    text = _normalize_text(name)
    for marker in DENIED_LICENSE_MARKERS:
        if re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text):
            return LicenseVerdict(False, f"license not allowed for monetized blogs: {name}")
    normalized = normalize_license(name)
    if normalized is None:
        return LicenseVerdict(False, f"unknown license: {name}")
    if normalized not in ALLOWED_LICENSES:
        return LicenseVerdict(False, f"license not in allowlist: {name}")
    if normalized in ATTRIBUTION_REQUIRED_LICENSES and not (author or "").strip():
        return LicenseVerdict(False, "attribution required but author is missing")
    return LicenseVerdict(True, "")


@dataclass
class ImageResult:
    """A normalized image candidate, identical regardless of provider."""

    provider: str
    image_url: str
    page_url: str
    title: str = ""
    description: str | None = None
    thumb_url: str | None = None
    author: str | None = None
    license: str | None = None
    license_url: str | None = None
    attribution_required: bool = False
    usage_notes: str | None = None
    mime: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    relevance: float = 0.0
    retrieved_at: datetime | None = None

    def dedupe_key(self) -> str:
        """Canonical identity: normalized image URL (trailing slash stripped)."""
        return (self.image_url or "").strip().rstrip("/")

    def validate(self) -> list[str]:
        """Structural checks on provider-supplied metadata (untrusted).

        Returns a list of problems; an empty list means the record is
        structurally usable. License acceptance is a separate concern handled
        by verify_license(); MIME/format and size checks arrive with download
        handling in a later phase.
        """
        problems: list[str] = []
        for field_name in ("image_url", "page_url"):
            value = (getattr(self, field_name) or "").strip()
            if not value:
                problems.append(f"{field_name} is missing")
            elif not value.startswith("https://"):
                problems.append(f"{field_name} must be an https URL")
        return problems


class ImageProvider(abc.ABC):
    """Strict interface every image provider must implement.

    Providers are stateless: no DB, no shared mutable config. A provider may
    read settings at call time if it needs one (e.g. an optional key). No
    provider may make arbitrary network requests on behalf of user-supplied
    URLs; requests are confined to the provider's own allowlisted hosts.
    """

    name: str = ""
    display_name: str = ""
    enabled_by_default: bool = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.name and cls.__name__ != "ImageProvider":
            cls.name = cls.__name__.lower()

    @abc.abstractmethod
    async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
        """Return normalized image candidates for the query.

        Must raise ImageProviderError (or a subclass) on any failure so the
        caller can record the error and degrade gracefully.
        """

    def is_configured(self) -> bool:
        """Whether this provider can run (True for keyless providers)."""
        return True

    async def close(self) -> None:  # pragma: no cover - optional override
        """Release any resources held by the provider, if applicable."""


class ImageProviderError(RuntimeError):
    """Raised by a provider when it cannot complete a search.

    Providers should attach the underlying cause as `__cause__` so the
    caller can log it without swallowing details.
    """
