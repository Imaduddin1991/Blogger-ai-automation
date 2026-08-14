"""Async client for the local Ollama server (/api/chat).

Single AI provider for v1 (local, free). Async so generation calls never
block the event loop; the pipeline is serialized to protect RAM/CPU, but
the HTTP layer stays async and time-bounded.
"""

from __future__ import annotations

import json

import httpx

from app.config import get_settings


class OllamaUnavailableError(RuntimeError):
    """Ollama is not running or unreachable (network-level failure)."""


class OllamaResponseError(RuntimeError):
    """Ollama answered with an error status or malformed payload."""


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama_url).rstrip("/")
        self.model = model or settings.ollama_default_model
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        format: str | None = None,
        options: dict | None = None,
        timeout: float | None = None,
    ) -> str:
        """Run a non-streaming chat completion; returns the assistant text."""
        payload: dict = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                resp = await client.post(self._url("/api/chat"), json=payload)
        except httpx.HTTPError as exc:
            raise OllamaUnavailableError(
                f"cannot reach Ollama at {self.base_url}: {type(exc).__name__}"
            ) from exc
        if resp.status_code != 200:
            raise OllamaResponseError(
                f"Ollama HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise OllamaResponseError("Ollama returned non-JSON response") from exc
        return str(data.get("message", {}).get("content", "")).strip()

    async def chat_json(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        options: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        """Chat with `format=json` (Ollama guarantees valid JSON)."""
        text = await self.chat(
            messages, model=model, format="json", options=options, timeout=timeout
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OllamaResponseError("model returned text, not JSON") from exc
        if not isinstance(data, dict):
            raise OllamaResponseError("model returned non-object JSON")
        return data

    async def is_available(self, timeout: float = 2.0) -> bool:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self._url("/api/tags"))
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self, timeout: float = 2.0) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self._url("/api/tags"))
        except httpx.HTTPError as exc:
            raise OllamaUnavailableError(
                f"cannot reach Ollama at {self.base_url}"
            ) from exc
        if resp.status_code != 200:
            raise OllamaResponseError(f"Ollama HTTP {resp.status_code}")
        return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
