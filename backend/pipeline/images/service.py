"""Image data-layer helpers (Phase 4C).

Pure mapping and persistence support: converts a validated provider record
into an `Image` row. The pipeline orchestration (search jobs, state changes,
API endpoints) arrives in Phase 4D; this module only owns the data mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone

from db.models import Image
from pipeline.images.providers.base import ImageResult
from pipeline.images.status import IMAGE_STATUS_CANDIDATE
from pipeline.images.validate import validate_image_metadata


def image_result_to_row(result: ImageResult, *, article_id: int | None = None) -> Image:
    """Map a provider record to a persisted `Image` row.

    Runs the full validation layer first; an unusable candidate raises
    ValueError with the rejection reasons instead of persisting.
    """
    problems = validate_image_metadata(result)
    if problems:
        raise ValueError("; ".join(problems))
    return Image(
        article_id=article_id,
        provider=result.provider,
        url=result.image_url,
        page_url=result.page_url,
        caption=result.title or None,
        alt=result.description or None,
        attribution=None,  # rendered credit line is built at render time
        license=result.license or None,
        license_url=result.license_url or None,
        author=result.author or None,
        attribution_required=result.attribution_required,
        usage_notes=result.usage_notes or None,
        thumb_url=result.thumb_url or None,
        mime=result.mime or None,
        width=result.width,
        height=result.height,
        file_size=result.file_size,
        relevance=result.relevance,
        retrieved_at=result.retrieved_at or datetime.now(timezone.utc),
        status=IMAGE_STATUS_CANDIDATE,
    )
