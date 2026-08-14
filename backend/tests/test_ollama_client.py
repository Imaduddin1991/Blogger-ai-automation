"""Ollama client tests with a mocked HTTP transport (no live server)."""

import httpx
import pytest

from services.ollama_client import (
    OllamaClient,
    OllamaResponseError,
    OllamaUnavailableError,
)

BASE = "http://ollama.test:11434"


@pytest.fixture
def client(monkeypatch):
    c = OllamaClient(base_url=BASE, model="test-model", timeout=5.0)
    monkeypatch.setattr(
        "services.ollama_client.httpx.AsyncClient", FakeAsyncClient
    )
    return c


class FakeTransport:
    """Responds to POST /api/chat and GET /api/tags based on configured stubs."""

    status_code = 200
    payload: dict = {}
    raise_http_error = False

    @classmethod
    def reset(cls):
        cls.status_code = 200
        cls.payload = {}
        cls.raise_http_error = False


class FakeAsyncClient:
    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None):
        if FakeTransport.raise_http_error:
            raise httpx.ConnectError("boom", request=httpx.Request("POST", url))
        resp = httpx.Response(
            FakeTransport.status_code,
            json=FakeTransport.payload,
            request=httpx.Request("POST", url),
        )
        return resp

    async def get(self, url):
        if FakeTransport.raise_http_error:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
        resp = httpx.Response(
            FakeTransport.status_code,
            json=FakeTransport.payload,
            request=httpx.Request("GET", url),
        )
        return resp


async def test_chat_returns_content(client):
    FakeTransport.reset()
    FakeTransport.payload = {"message": {"role": "assistant", "content": "hello"}}
    assert await client.chat([{"role": "user", "content": "hi"}]) == "hello"


async def test_chat_json_parses(client):
    FakeTransport.reset()
    FakeTransport.payload = {"message": {"role": "assistant", "content": '{"ok": 1}'}}
    assert await client.chat_json([{"role": "user", "content": "hi"}]) == {"ok": 1}


async def test_chat_raises_on_non_200(client):
    FakeTransport.reset()
    FakeTransport.status_code = 404
    with pytest.raises(OllamaResponseError):
        await client.chat([{"role": "user", "content": "hi"}])


async def test_chat_raises_on_network_error(client):
    FakeTransport.reset()
    FakeTransport.raise_http_error = True
    with pytest.raises(OllamaUnavailableError):
        await client.chat([{"role": "user", "content": "hi"}])


async def test_is_available(client):
    FakeTransport.reset()
    FakeTransport.status_code = 200
    FakeTransport.payload = {"models": []}
    assert await client.is_available() is True


async def test_is_available_false_on_error(client):
    FakeTransport.reset()
    FakeTransport.raise_http_error = True
    assert await client.is_available() is False


async def test_list_models(client):
    FakeTransport.reset()
    FakeTransport.payload = {"models": [{"name": "qwen2.5:1.5b"}, {"name": "nope"}]}
    assert await client.list_models() == ["qwen2.5:1.5b", "nope"]


async def test_chat_sends_json_format_and_options(client):
    FakeTransport.reset()
    FakeTransport.payload = {"message": {"content": "{}"}}
    sent: dict = {}

    class RecordingClient(FakeAsyncClient):
        async def post(self, url, json=None):
            sent.update(json or {})
            return await super().post(url, json=json)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("services.ollama_client.httpx.AsyncClient", RecordingClient)
    await client.chat_json(
        [{"role": "user", "content": "hi"}], options={"temperature": 0.3}
    )
    assert sent.get("format") == "json"
    assert sent.get("options") == {"temperature": 0.3}
    assert sent.get("model") == "test-model"
