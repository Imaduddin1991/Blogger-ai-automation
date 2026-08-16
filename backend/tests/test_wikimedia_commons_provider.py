"""Wikimedia Commons provider tests. All HTTP is mocked — no live network."""

import httpx
import pytest

from pipeline.images.providers import commons
from pipeline.images.providers.base import ImageProviderError
from pipeline.images.providers.registry import get_provider, provider_names


class Transport:
    status_code = 200
    payload: dict = {}
    raw_text: str | None = None
    raise_http_error = False

    @classmethod
    def reset(cls):
        cls.status_code = 200
        cls.payload = {}
        cls.raw_text = None
        cls.raise_http_error = False


class FakeAsyncClient:
    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(
        self,
        url,
        params=None,
        timeout=None,
        follow_redirects=False,
        headers=None,
    ):
        if Transport.raise_http_error:
            raise httpx.ReadTimeout("slow", request=httpx.Request("GET", url))
        if Transport.raw_text is not None:
            resp = httpx.Response(
                Transport.status_code, text=Transport.raw_text, request=httpx.Request("GET", url)
            )
        else:
            resp = httpx.Response(
                Transport.status_code,
                json=Transport.payload,
                request=httpx.Request("GET", url),
            )
        return resp


@pytest.fixture(autouse=True)
def _mock_http(monkeypatch):
    Transport.reset()
    monkeypatch.setattr(commons.httpx, "AsyncClient", FakeAsyncClient)


def _info(**overrides) -> dict:
    info = {
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Cat_on_Windowsill.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Cat_on_Windowsill.jpg",
        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Cat_on_Windowsill.jpg/400px-Cat_on_Windowsill.jpg",
        "width": 1600,
        "height": 1200,
        "size": 234567,
        "mime": "image/jpeg",
        "mediatype": "BITMAP",
        "extmetadata": {
            "LicenseShortName": {"value": "CC BY-SA 4.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
            "UsageTerms": {"value": "Creative Commons Attribution-ShareAlike 4.0"},
            "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Jane_Doe">Jane Doe</a>'},
            "AttributionRequired": {"value": "true"},
            "ImageDescription": {"value": "A cat lounging on a windowsill"},
        },
    }
    info.update(overrides)
    return info


def _page(title: str = "File:Cat_on_Windowsill.jpg", index: int = 1, **info_overrides) -> dict:
    return {
        "pageid": index + 100,
        "ns": 6,
        "title": title,
        "index": index,
        "imageinfo": [_info(**info_overrides)],
    }


def _payload(*pages: object) -> dict:
    return {"batchcomplete": "", "query": {"pages": list(pages)}}


async def test_successful_search_normalizes_result():
    Transport.payload = _payload(_page())
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    r = results[0]
    assert r.provider == "commons"
    assert r.image_url.startswith("https://upload.wikimedia.org")
    assert r.page_url == "https://commons.wikimedia.org/wiki/File:Cat_on_Windowsill.jpg"
    assert r.title == "Cat on Windowsill"
    assert r.author == "Jane Doe"
    assert r.license == "CC BY-SA 4.0"
    assert r.license_url == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert r.attribution_required is True
    assert r.mime == "image/jpeg"
    assert r.width == 1600
    assert r.height == 1200
    assert r.file_size == 234567
    assert r.thumb_url and "400px" in r.thumb_url
    assert r.usage_notes
    assert 0.0 <= r.relevance <= 1.0
    assert r.validate() == []


async def test_relevance_is_deterministic():
    Transport.payload = _payload(_page())
    results = await commons.CommonsProvider().search("cat")
    assert results[0].relevance == 1.0


async def test_object_name_preferred_over_filename():
    Transport.payload = _payload(
        _page(
            title="File:Cat_on_Windowsill.jpg",
            index=1,
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "Artist": {"value": "Jane Doe"},
                "ObjectName": {"value": "Renamed Title"},
            },
        )
    )
    results = await commons.CommonsProvider().search("cats")
    assert results[0].title == "Renamed Title"


async def test_multiple_results_preserve_provider_order():
    Transport.payload = _payload(
        _page(title="File:B.jpg", index=2),
        _page(title="File:A.jpg", index=1),
    )
    results = await commons.CommonsProvider().search("cats")
    assert [r.title for r in results] == ["A", "B"]


async def test_empty_results():
    Transport.payload = {"batchcomplete": "", "query": {"pages": []}}
    assert await commons.CommonsProvider().search("zzz_nothing") == []


async def test_missing_pages_key_is_empty():
    Transport.payload = {"batchcomplete": ""}
    assert await commons.CommonsProvider().search("cats") == []


async def test_valid_cc0():
    Transport.payload = _payload(
        _page(
            title="File:CC0.jpg",
            index=1,
            extmetadata={
                "LicenseShortName": {"value": "CC0"},
                "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/zero/1.0/"},
                "Artist": {"value": ""},
                "ObjectName": {"value": "CC0 image"},
            },
        )
    )
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    assert results[0].license == "CC0"
    assert results[0].attribution_required is False
    assert results[0].author is None


async def test_valid_public_domain():
    Transport.payload = _payload(
        _page(
            title="File:PD.jpg",
            index=1,
            extmetadata={
                "LicenseShortName": {"value": "Public domain"},
                "Artist": {"value": ""},
                "ObjectName": {"value": "PD image"},
            },
        )
    )
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    assert results[0].license == "Public domain"
    assert results[0].attribution_required is False


async def test_valid_cc_by():
    Transport.payload = _payload(
        _page(
            title="File:BY.jpg",
            index=1,
            extmetadata={
                "LicenseShortName": {"value": "CC BY 4.0"},
                "Artist": {"value": "Jane Doe"},
                "ObjectName": {"value": "BY image"},
            },
        )
    )
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    assert results[0].license == "CC BY 4.0"
    assert results[0].attribution_required is True


async def test_valid_cc_by_sa():
    Transport.payload = _payload(_page())
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    assert results[0].license == "CC BY-SA 4.0"
    assert results[0].attribution_required is True


@pytest.mark.parametrize(
    "license_name",
    [
        "CC BY-NC 4.0",
        "CC BY-NC-SA 4.0",
        "Attribution-NonCommercial-ShareAlike 4.0",
        "CC BY-ND 4.0",
        "Attribution-NoDerivatives 4.0",
        "GFDL",
        "Some made up license",
    ],
)
async def test_rejected_licenses_are_dropped(license_name):
    Transport.payload = _payload(
        _page(
            title="File:Bad.jpg",
            index=1,
            extmetadata={
                "LicenseShortName": {"value": license_name},
                "Artist": {"value": "Jane Doe"},
                "ObjectName": {"value": "Bad image"},
            },
        )
    )
    assert await commons.CommonsProvider().search("cats") == []


async def test_missing_extmetadata_is_dropped():
    Transport.payload = _payload(_page(index=1, extmetadata={}))
    assert await commons.CommonsProvider().search("cats") == []


async def test_missing_license_metadata_is_dropped():
    Transport.payload = _payload(
        _page(index=1, extmetadata={"Artist": {"value": "Jane Doe"}})
    )
    assert await commons.CommonsProvider().search("cats") == []


async def test_attribution_license_without_author_is_dropped():
    Transport.payload = _payload(
        _page(
            index=1,
            extmetadata={
                "LicenseShortName": {"value": "CC BY 4.0"},
                "Artist": {"value": ""},
                "ObjectName": {"value": "No author"},
            },
        )
    )
    assert await commons.CommonsProvider().search("cats") == []


async def test_missing_image_url_is_dropped():
    Transport.payload = _payload(
        _page(index=1, url="", descriptionurl="https://commons.wikimedia.org/wiki/File:X.jpg")
    )
    assert await commons.CommonsProvider().search("cats") == []


async def test_missing_page_url_is_dropped():
    Transport.payload = _payload(_page(index=1, descriptionurl=""))
    assert await commons.CommonsProvider().search("cats") == []


async def test_malformed_candidate_skipped_not_crash():
    Transport.payload = _payload(
        "garbage",
        {"pageid": 999, "ns": 6, "title": "File:Broken.jpg", "index": 1, "imageinfo": ["not-a-dict"]},
        _page(title="File:Good.jpg", index=2),
    )
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    assert results[0].title == "Good"


async def test_non_integer_limit_defaults_to_sane_batch():
    Transport.payload = _payload(_page())
    results = await commons.CommonsProvider().search("cats", limit=None)  # type: ignore[arg-type]
    assert len(results) == 1


async def test_invalid_dimensions_normalized_to_none():
    Transport.payload = _payload(
        _page(index=1, width="abc", height="-5", size="huge")
    )
    results = await commons.CommonsProvider().search("cats")
    assert len(results) == 1
    assert results[0].width is None
    assert results[0].height is None
    assert results[0].file_size is None


async def test_http_license_url_dropped_from_result():
    Transport.payload = _payload(
        _page(
            index=1,
            extmetadata={
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                "LicenseUrl": {"value": "http://creativecommons.org/licenses/by-sa/4.0/"},
                "Artist": {"value": "Jane Doe"},
                "ObjectName": {"value": "X"},
            },
        )
    )
    results = await commons.CommonsProvider().search("cats")
    assert results[0].license_url is None


async def test_timeout_raises_provider_error():
    Transport.raise_http_error = True
    with pytest.raises(ImageProviderError, match="network error"):
        await commons.CommonsProvider().search("cats")


async def test_http_failure_raises_provider_error():
    Transport.status_code = 500
    with pytest.raises(ImageProviderError, match="HTTP 500"):
        await commons.CommonsProvider().search("cats")


async def test_invalid_json_raises_provider_error():
    Transport.raw_text = "<html>oops</html>"
    with pytest.raises(ImageProviderError, match="non-JSON"):
        await commons.CommonsProvider().search("cats")


async def test_api_error_response_raises_provider_error():
    Transport.payload = {"error": {"code": "badvalue", "info": "unknown param"}}
    with pytest.raises(ImageProviderError, match="Commons API error: unknown param"):
        await commons.CommonsProvider().search("cats")


async def test_limit_is_bounded():
    sent: dict = {}

    class RecordingClient(FakeAsyncClient):
        async def get(self, url, params=None, timeout=None, follow_redirects=False, headers=None):
            sent.update(params or {})
            return await super().get(url, params=params)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(commons.httpx, "AsyncClient", RecordingClient)
    Transport.payload = _payload(_page())
    await commons.CommonsProvider().search("cats", limit=500)
    assert sent["gsrlimit"] == "50"
    assert "filetype:bitmap|filetype:drawing" in sent["gsrsearch"]
    assert sent["gsrnamespace"] == "6"
    assert sent["iiurlwidth"] == "400"


async def test_limit_default_and_exact():
    sent: dict = {}

    class RecordingClient(FakeAsyncClient):
        async def get(self, url, params=None, timeout=None, follow_redirects=False, headers=None):
            sent.update(params or {})
            return await super().get(url, params=params)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(commons.httpx, "AsyncClient", RecordingClient)
    Transport.payload = _payload(_page())
    await commons.CommonsProvider().search("cats", limit=3)
    assert sent["gsrlimit"] == "3"


async def test_provider_registration():
    assert "commons" in provider_names()
    provider = get_provider("commons")
    assert isinstance(provider, commons.CommonsProvider)
    assert provider.name == "commons"
    assert provider.is_configured() is True
