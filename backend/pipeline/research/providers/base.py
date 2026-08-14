"""ResearchProvider contract.

The core research pipeline depends only on this interface, never on a
concrete provider. To add a free provider later: implement ResearchProvider,
register it, done. The pipeline, article generation, and data model do not
change.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

import httpx


@dataclass
class Source:
    """A normalized research result, identical regardless of provider."""

    provider: str
    title: str
    url: str
    snippet: str = ""
    relevance: float = 0.0
    license: str | None = None

    def dedupe_key(self) -> str:
        """Two sources are the same if they point at the same URL.

        Keyed on the normalized URL alone (not provider) so the same page
        returned by Wikimedia and DuckDuckGo merges into one source.
        """
        return self.url.strip().rstrip("/")


class ResearchProvider(abc.ABC):
    """Strict interface every research provider must implement.

    Providers are stateless: no DB, no shared mutable config. A provider
    may read settings at call time if it needs one (e.g. an optional key).
    """

    name: str = ""
    display_name: str = ""
    enabled_by_default: bool = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.name and cls.__name__ != "ResearchProvider":
            cls.name = cls.__name__.lower()

    @abc.abstractmethod
    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        """Return normalized sources for the topic.

        Must raise ResearchProviderError (or a subclass) on failure so the
        orchestrator can record the error and continue with other providers.
        """

    def is_configured(self) -> bool:
        """Whether this provider can run (True for keyless providers)."""
        return True

    async def close(self) -> None:  # pragma: no cover - optional override
        """Release any resources held by the provider, if applicable."""


class ResearchProviderError(RuntimeError):
    """Raised by a provider when it cannot complete a search.

    Providers should attach the underlying cause as `__cause__` so the
    orchestrator can log it without swallowing details.
    """


@dataclass
class ProviderResult:
    provider: str
    sources: list[Source] = field(default_factory=list)
    error: str | None = None


# Wikimedia/Wikidata reject requests without a descriptive User-Agent that
# carries an https contact URL (policy: https://w.wiki/4wJS). Keyless
# providers use this shared client so one fix covers them all.
USER_AGENT = "blogger-ai-automation/0.1 (https://localhost; self-hosted local tool)"


async def fetch_json(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 10.0,
    ok_statuses: tuple[int, ...] = (200,),
) -> dict:
    """Shared async HTTP fetch used by keyless providers.

    Async so providers can run concurrently under asyncio.gather without
    blocking the event loop. `ok_statuses` lets a provider treat extra
    statuses as success (e.g. DuckDuckGo's 202 "no instant answer"), which
    fetch_json then returns as an empty dict instead of raising.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, params=params, timeout=timeout, follow_redirects=True, headers=headers
            )
    except httpx.HTTPError as exc:
        raise ResearchProviderError(f"network error: {type(exc).__name__}") from exc
    if resp.status_code not in ok_statuses:
        raise ResearchProviderError(f"HTTP {resp.status_code} for {url}")
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise ResearchProviderError("non-JSON response") from exc
