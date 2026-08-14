"""Wikidata provider: entity search REST API.

https://www.wikidata.org/w/api.php?action=wbsearchentities&search=<topic>
Free, keyless. Adds structured/entity coverage alongside Wikipedia prose.
"""

from __future__ import annotations

from pipeline.research.providers.base import ResearchProvider, Source, fetch_json
from pipeline.research.providers.registry import register

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"


@register
class WikidataProvider(ResearchProvider):
    name = "wikidata"
    display_name = "Wikidata"

    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        data = await fetch_json(
            _WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": topic,
                "language": "en",
                "format": "json",
                "limit": limit,
                "type": "item",
            },
        )
        sources: list[Source] = []
        for item in data.get("search") or []:
            qid = item.get("id") or ""
            label = item.get("label") or ""
            if not qid or not label:
                continue
            sources.append(
                Source(
                    provider=self.name,
                    title=label,
                    url=f"https://www.wikidata.org/wiki/{qid}",
                    snippet=(item.get("description") or "").strip(),
                    relevance=1.0 if (item.get("description") or "").strip() else 0.6,
                )
            )
        return sources
