"""Research orchestrator.

Runs the enabled ResearchProviders for a topic, merges and deduplicates
their normalized sources, and reports per-provider errors. The pipeline
depends on this module and the provider interface only; concrete providers
are loaded through the registry.

Phase 1: source gathering + merge. Phase 2 adds LLM summarization and
DB caching (per topic_key).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pipeline.research.providers.base import Source
from pipeline.research.providers.registry import enabled_providers


@dataclass
class ResearchOutput:
    topic: str
    sources: list[Source] = field(default_factory=list)
    provider_errors: list[tuple[str, str]] = field(default_factory=list)
    providers_attempted: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Share of attempted providers that succeeded (0..1)."""
        attempted = len(self.providers_attempted)
        if attempted == 0:
            return 0.0
        failed = len(self.provider_errors)
        return max(0.0, min(1.0, (attempted - failed) / attempted))


async def run_research(topic: str, limit: int = 5, providers: list | None = None) -> ResearchOutput:
    """Gather sources from all enabled providers, merging and deduplicating.

    A failing provider never fails the whole research run: its error is
    recorded and the rest continue (graceful degradation).
    """
    topic = (topic or "").strip()
    pool = providers if providers is not None else enabled_providers()

    outcomes = await asyncio.gather(
        *(p.search(topic, limit=limit) for p in pool),
        return_exceptions=True,
    )

    merged: dict[str, Source] = {}
    errors: list[tuple[str, str]] = []
    for provider, outcome in zip(pool, outcomes):
        if isinstance(outcome, BaseException):
            errors.append((provider.name, str(outcome)))
            continue
        for source in outcome:
            merged.setdefault(source.dedupe_key(), source)

    return ResearchOutput(
        topic=topic,
        sources=list(merged.values()),
        provider_errors=errors,
        providers_attempted=[p.name for p in pool],
    )
