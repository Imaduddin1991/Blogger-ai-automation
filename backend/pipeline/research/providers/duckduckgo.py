"""DuckDuckGo provider: Instant Answer API.

https://api.duckduckgo.com/?q=<topic>&format=json
Free, keyless. Coverage is shallow by design (instant answers + related
topics); this is a supplement, never the sole source.
"""

from __future__ import annotations

from pipeline.research.providers.base import ResearchProvider, Source, fetch_json
from pipeline.research.providers.registry import register

_DDG_API = "https://api.duckduckgo.com/"


def _walk_related(node, sources: list[Source]) -> None:
    text = (node.get("Text") or "").strip()
    url = (node.get("FirstURL") or "").strip()
    if text and url:
        sources.append(Source(provider="duckduckgo", title=text.split(" - ")[0][:200], url=url, snippet=text))
    for sub in node.get("Topics") or []:
        _walk_related(sub, sources)


@register
class DuckDuckGoProvider(ResearchProvider):
    name = "duckduckgo"
    display_name = "DuckDuckGo Instant Answer"

    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        data = await fetch_json(
            _DDG_API,
            params={"q": topic, "format": "json", "no_html": 1, "skip_disambig": 1},
            ok_statuses=(200, 202),
        )
        sources: list[Source] = []
        abstract = (data.get("Abstract") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        if abstract and abstract_url:
            sources.append(Source(provider=self.name, title=(data.get("Heading") or topic)[:300], url=abstract_url, snippet=abstract))
        for node in data.get("RelatedTopics") or []:
            _walk_related(node, sources)
        return sources[:limit]
