"""Phase 4C: image validation / rejection rules."""

import pytest

from pipeline.images.providers.base import ImageResult
from pipeline.images.validate import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_FILE_SIZE,
    validate_image_metadata,
)


def _result(**overrides) -> ImageResult:
    result = ImageResult(
        provider="commons",
        image_url="https://upload.wikimedia.org/wikipedia/commons/a.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:A.jpg",
        title="A cat",
        license="CC BY-SA 4.0",
        author="Jane Doe",
        attribution_required=True,
        mime="image/jpeg",
        width=1600,
        height=1200,
        file_size=200000,
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def _problems(result: ImageResult) -> list[str]:
    return validate_image_metadata(result)


# --- License -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("license", "author", "attribution_required"),
    [
        ("CC0", None, False),
        ("Public domain", None, False),
        ("CC BY 4.0", "Jane Doe", True),
        ("CC BY-SA 4.0", "Jane Doe", True),
    ],
)
def test_license_accepted(license, author, attribution_required):
    assert _problems(_result(license=license, author=author, attribution_required=attribution_required)) == []


@pytest.mark.parametrize(
    "license",
    [
        "CC BY-NC 4.0",
        "CC BY-ND 4.0",
        "CC BY-NC-SA 4.0",
        "Attribution-NonCommercial-ShareAlike 4.0",
        "Fair use",
        "Some made up license",
    ],
)
def test_license_rejected(license):
    problems = _problems(_result(license=license))
    assert problems, "expected at least one rejection reason"
    assert any("license" in p for p in problems)


def test_license_missing_rejected():
    assert _problems(_result(license=None))


def test_attribution_license_missing_author_rejected():
    problems = _problems(_result(author=None))
    assert any("attribution" in p or "author" in p for p in problems)


def test_attribution_license_with_false_flag_rejected():
    problems = _problems(_result(attribution_required=False))
    assert any("attribution_required" in p for p in problems)


# --- URLs --------------------------------------------------------------------


def test_https_accepted():
    assert _problems(_result()) == []


def test_http_rejected():
    problems = _problems(_result(image_url="http://upload.wikimedia.org/a.jpg"))
    assert any("image_url" in p and "https" in p for p in problems)


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "file:///etc/passwd",
        "ftp://upload.wikimedia.org/a.jpg",
        "not a url with spaces",
        "https://",
    ],
)
def test_unsafe_or_invalid_url_rejected(bad_url):
    problems = _problems(_result(image_url=bad_url))
    assert any("image_url" in p for p in problems)


def test_page_url_rejected_when_unsafe():
    problems = _problems(_result(page_url="javascript:alert(1)"))
    assert any("page_url" in p for p in problems)


def test_optional_urls_rejected_when_unsafe():
    problems = _problems(
        _result(thumb_url="data:image/png;base64,AAAA", license_url="javascript:alert(1)")
    )
    assert any("thumb_url" in p for p in problems)
    assert any("license_url" in p for p in problems)


# --- SVG ---------------------------------------------------------------------


def test_svg_mime_rejected():
    problems = _problems(_result(mime="image/svg+xml"))
    assert any("svg" in p for p in problems)


def test_svg_url_rejected_even_with_raster_mime():
    problems = _problems(
        _result(image_url="https://upload.wikimedia.org/wikipedia/commons/a.svg", mime="image/png")
    )
    assert any("svg" in p for p in problems)


# --- MIME --------------------------------------------------------------------


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/webp", "image/gif"])
def test_raster_mime_accepted(mime):
    assert _problems(_result(mime=mime)) == []


@pytest.mark.parametrize("mime", ["image/tiff", "image/bmp", "text/html", "application/octet-stream", None])
def test_unsupported_mime_rejected(mime):
    problems = _problems(_result(mime=mime))
    assert any("mime" in p for p in problems)


# --- Size --------------------------------------------------------------------


def test_file_size_under_limit_accepted():
    assert _problems(_result(file_size=5 * 1024 * 1024)) == []


def test_file_size_exactly_at_limit_accepted():
    assert _problems(_result(file_size=MAX_IMAGE_FILE_SIZE)) == []


def test_file_size_over_limit_rejected():
    problems = _problems(_result(file_size=MAX_IMAGE_FILE_SIZE + 1))
    assert any("file size" in p for p in problems)


# --- Dimensions ---------------------------------------------------------------


def test_valid_dimensions_accepted():
    assert _problems(_result(width=1600, height=1200)) == []


def test_zero_dimension_rejected():
    assert any("width" in p for p in _problems(_result(width=0)))
    assert any("height" in p for p in _problems(_result(height=0)))


def test_negative_dimension_rejected():
    assert any("width" in p for p in _problems(_result(width=-1)))


def test_malformed_dimension_rejected():
    assert any("width" in p for p in _problems(_result(width="1600")))
    assert any("width" in p for p in _problems(_result(width=1600.5)))


def test_oversized_dimension_rejected():
    problems = _problems(_result(width=MAX_IMAGE_DIMENSION + 1))
    assert any("width" in p for p in problems)


# --- Combination ---------------------------------------------------------------


def test_multiple_problems_are_all_reported():
    problems = _problems(
        _result(
            image_url="http://upload.wikimedia.org/a.svg",
            license="CC BY-NC 4.0",
            mime="image/tiff",
            file_size=MAX_IMAGE_FILE_SIZE + 1,
            width=-5,
        )
    )
    assert any("license" in p for p in problems)
    assert any("image_url" in p for p in problems)
    assert any("svg" in p for p in problems)
    assert any("mime" in p for p in problems)
    assert any("file size" in p for p in problems)
    assert any("width" in p for p in problems)


# --- Dangerous extensions (Phase 4F hardening) ---------------------------------


@pytest.mark.parametrize(
    "ext",
    [
        ".exe", ".bat", ".cmd", ".sh", ".ps1", ".msi", ".com", ".scr",
        ".php", ".php3", ".js", ".vbs", ".jar", ".cgi", ".pl", ".py",
        ".doc", ".docx", ".zip", ".rar",
    ],
)
def test_dangerous_extension_on_image_url_rejected(ext):
    problems = _problems(
        _result(image_url=f"https://upload.wikimedia.org/wikipedia/commons/a{ext}")
    )
    assert any("dangerous extension" in p for p in problems)


@pytest.mark.parametrize("ext", [".exe", ".php", ".js", ".sh", ".zip"])
def test_dangerous_extension_on_thumb_url_rejected(ext):
    problems = _problems(
        _result(thumb_url=f"https://upload.wikimedia.org/wikipedia/commons/thumb/a{ext}")
    )
    assert any("thumb_url has dangerous extension" in p for p in problems)


def test_normal_image_url_extension_accepted():
    assert _problems(_result(image_url="https://upload.wikimedia.org/wikipedia/commons/photo.jpg")) == []


def test_dangerous_extension_with_valid_raster_mime_rejected():
    """A spoofed MIME type should not bypass the extension check."""
    problems = _problems(
        _result(
            image_url="https://upload.wikimedia.org/wikipedia/commons/a.exe",
            mime="image/jpeg",
        )
    )
    assert any("dangerous extension" in p for p in problems)
