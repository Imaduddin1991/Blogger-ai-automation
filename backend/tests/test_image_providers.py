"""Phase 4A: image provider abstraction, registry, and license policy."""

import pytest

from pipeline.images.providers.base import (
    ALLOWED_LICENSES,
    ImageProvider,
    ImageResult,
    LicenseVerdict,
    normalize_license,
    verify_license,
)
from pipeline.images.providers.registry import (
    ProviderRegistryError,
    all_providers,
    enabled_providers,
    get_provider,
    provider_names,
    register,
)


def _result(**overrides) -> ImageResult:
    result = ImageResult(
        provider="commons",
        image_url="https://upload.wikimedia.org/wikipedia/commons/thumb/a.jpg",
        page_url="https://commons.wikimedia.org/wiki/File:A.jpg",
        title="A cat",
        license="CC BY-SA 4.0",
        author="Jane Doe",
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


# --- ImageResult validation -------------------------------------------------


def test_image_result_valid():
    assert _result().validate() == []


def test_image_result_missing_urls():
    problems = _result(image_url="", page_url="").validate()
    assert "image_url is missing" in problems
    assert "page_url is missing" in problems


def test_image_result_rejects_non_https_urls():
    problems = _result(
        image_url="http://upload.wikimedia.org/x.jpg",
        page_url="ftp://commons.wikimedia.org/x",
    ).validate()
    assert "image_url must be an https URL" in problems
    assert "page_url must be an https URL" in problems


def test_image_result_dedupe_key_normalizes_trailing_slash():
    a = _result(image_url="https://upload.wikimedia.org/a.jpg")
    b = _result(image_url="https://upload.wikimedia.org/a.jpg/")
    assert a.dedupe_key() == b.dedupe_key()


def test_image_result_dedupe_key_distinguishes_distinct_urls():
    a = _result(image_url="https://upload.wikimedia.org/a.jpg")
    b = _result(image_url="https://upload.wikimedia.org/b.jpg")
    assert a.dedupe_key() != b.dedupe_key()


# --- Provider contract -------------------------------------------------------


def test_provider_is_abstract():
    with pytest.raises(TypeError):
        ImageProvider()  # type: ignore[abstract]


def test_provider_requires_search():
    class NoSearch(ImageProvider):
        pass

    with pytest.raises(TypeError):
        NoSearch()  # type: ignore[abstract]


def test_provider_defaults():
    class Fake(ImageProvider):
        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return []

    provider = Fake()
    assert provider.name == "fake"  # auto-derived
    assert provider.display_name == ""
    assert provider.enabled_by_default is True
    assert provider.is_configured() is True
    assert isinstance(provider.search, object)


async def test_provider_search_returns_normalized_results():
    class Fake(ImageProvider):
        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return [_result()]

    results = await Fake().search("cats")
    assert len(results) == 1
    assert results[0].provider == "commons"


# --- Registry ----------------------------------------------------------------


def test_register_and_lookup():
    class FakeProvider(ImageProvider):
        name = "image_fake"
        display_name = "Fake"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return []

    registered = register(FakeProvider)
    assert registered is FakeProvider
    instance = get_provider("image_fake")
    assert isinstance(instance, FakeProvider)
    assert "image_fake" in provider_names()


def test_duplicate_registration_raises():
    class Dupe(ImageProvider):
        name = "image_dupe"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return []

    register(Dupe)
    with pytest.raises(ProviderRegistryError):
        register(Dupe)


def test_unknown_provider_raises():
    with pytest.raises(ProviderRegistryError):
        get_provider("image_does_not_exist")


def test_enabled_providers_filters_disabled_and_unconfigured():
    class On(ImageProvider):
        name = "image_on"

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return []

    class Off(ImageProvider):
        name = "image_off"
        enabled_by_default = False

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return []

    class NoKey(ImageProvider):
        name = "image_nokey"

        def is_configured(self) -> bool:
            return False

        async def search(self, query: str, limit: int = 8) -> list[ImageResult]:
            return []

    register(On)
    register(Off)
    register(NoKey)

    enabled_names = [p.name for p in enabled_providers()]
    assert "image_on" in enabled_names
    assert "image_off" not in enabled_names
    assert "image_nokey" not in enabled_names
    assert all(isinstance(p, ImageProvider) for p in all_providers())


# --- License policy: accepted -------------------------------------------------


@pytest.mark.parametrize(
    "license_name",
    [
        "CC0",
        "CC0 1.0 Universal",
        "Creative Commons CC0 1.0 Universal",
        "Public domain",
        "PD",
        "CC BY 4.0",
        "CC BY-SA 4.0",
        "cc-by-sa-4.0",
        "Attribution-ShareAlike 4.0 International",
    ],
)
def test_license_accepted(license_name):
    verdict = verify_license(license_name, author="Jane Doe")
    assert verdict.allowed is True, verdict.reason


def test_all_allowlisted_licenses_are_accepted():
    for key in ALLOWED_LICENSES:
        verdict = verify_license(key, author="Jane Doe")
        assert verdict.allowed is True, f"{key}: {verdict.reason}"


def test_public_domain_needs_no_author():
    assert verify_license("Public domain").allowed is True
    assert verify_license("CC0").allowed is True


def test_attribution_licenses_require_author():
    for license_name in ("CC BY 4.0", "CC BY-SA 4.0", "cc-by-4.0"):
        verdict = verify_license(license_name, author=None)
        assert verdict.allowed is False
        assert "attribution required" in verdict.reason


def test_attribution_license_whitespace_author_rejected():
    verdict = verify_license("CC BY 4.0", author="   ")
    assert verdict.allowed is False


# --- License policy: rejected / unknown ---------------------------------------


@pytest.mark.parametrize(
    "license_name",
    [
        "CC BY-NC 4.0",
        "CC BY-ND 4.0",
        "CC BY-NC-SA 4.0",
        "CC BY-NC-ND 4.0",
        "Attribution-NonCommercial-ShareAlike 4.0",
        "Attribution-NoCommercial-ShareAlike 4.0",
        "Attribution-NoCommercial 4.0",
        "Attribution-NoDerivatives 4.0",
        "Attribution-NoDerivs 4.0",
        "Fair use",
        "Non-free",
        "Copyrighted",
        "Permission",
        "All rights reserved",
        "GFDL",
        "Some made up license",
    ],
)
def test_license_rejected(license_name):
    verdict = verify_license(license_name, author="Jane Doe")
    assert verdict.allowed is False
    assert verdict.reason  # a visible reason is required


def test_license_missing_rejected():
    for missing in (None, "", "   "):
        verdict = verify_license(missing)
        assert verdict.allowed is False
        assert verdict.reason


def test_verify_license_returns_verdict_shape():
    verdict = verify_license("CC BY 4.0", author="Jane Doe")
    assert isinstance(verdict, LicenseVerdict)
    assert isinstance(verdict.allowed, bool)
    assert isinstance(verdict.reason, str)


def test_license_policy_is_case_and_spacing_tolerant():
    assert verify_license("cc by-sa 4.0", author="Jane").allowed is True
    assert verify_license("  CC   BY  4.0  ", author="Jane").allowed is True


# --- normalize_license ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CC0", "cc0"),
        ("Creative Commons CC0 1.0 Universal", "cc0"),
        ("Public domain", "public domain"),
        ("PD", "public domain"),
        ("CC BY 4.0", "cc by"),
        ("CC BY-SA 4.0", "cc by-sa"),
        ("Attribution-ShareAlike 4.0 International", "cc by-sa"),
    ],
)
def test_normalize_license_mapping(raw, expected):
    assert normalize_license(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "GFDL", "made up", "Fair use"])
def test_normalize_license_unknown_returns_none(raw):
    assert normalize_license(raw) is None


# --- Malformed provider output -------------------------------------------------


def test_malformed_provider_result_detected():
    malformed = _result(image_url="", page_url="not-a-url")
    problems = malformed.validate()
    assert "image_url is missing" in problems
    assert "page_url must be an https URL" in problems
