"""Wikimedia provider: Wikipedia REST API search.

https://en.wikipedia.org/w/rest.php/v1/search/page?q=<topic>
Free, keyless, stable. Provides encyclopedic coverage but is not assumed to
cover every topic comprehensively (see discovery doc, research requirements).
"""

from __future__ import annotations

from urllib.parse import quote

from pipeline.research.providers.base import (
    ResearchProvider,
    Source,
    compute_relevance,
    fetch_json,
)
from pipeline.research.providers.registry import register

_WIKI_REST = "https://en.wikipedia.org/w/rest.php/v1/search/page"


@register
class WikimediaProvider(ResearchProvider):
    name = "wikimedia"
    display_name = "Wikipedia (Wikimedia REST)"

    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        data = await fetch_json(_WIKI_REST, params={"q": topic, "limit": limit})
        pages = data.get("pages") or []
        sources: list[Source] = []
        for page in pages:
            title = page.get("title") or ""
            if not title:
                continue
            url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            snippet = (page.get("description") or "").strip()
            sources.append(
                Source(
                    provider=self.name,
                    title=title,
                    url=url,
                    snippet=snippet,
                    relevance=compute_relevance(topic, title, snippet),
                )
            )
        return sources
