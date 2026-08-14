"""Research orchestrator: merge, URL dedup, graceful degradation, coverage.

Uses fake providers so tests never touch the network.
"""

from pipeline.research import run_research
from pipeline.research.providers.base import ResearchProvider, ResearchProviderError, Source


class OkProvider(ResearchProvider):
    name = "ok"
    display_name = "OK"

    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        return [
            Source(provider=self.name, title=f"{topic} A", url="https://example.com/a"),
            Source(provider=self.name, title=f"{topic} B", url="https://example.com/b"),
        ]


class FailingProvider(ResearchProvider):
    name = "failing"
    display_name = "Failing"

    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        raise ResearchProviderError("boom")


class OverlappingProvider(ResearchProvider):
    """Returns the same URL as OkProvider: must dedupe away."""

    name = "overlap"
    display_name = "Overlap"

    async def search(self, topic: str, limit: int = 5) -> list[Source]:
        return [Source(provider=self.name, title=f"{topic} A (dup)", url="https://example.com/a")]


async def test_merges_sources():
    out = await run_research("topic", providers=[OkProvider()])
    assert len(out.sources) == 2
    assert out.coverage == 1.0
    assert out.providers_attempted == ["ok"]


async def test_failing_provider_degrades_gracefully():
    out = await run_research("topic", providers=[OkProvider(), FailingProvider()])
    assert len(out.sources) == 2
    assert len(out.provider_errors) == 1
    assert "boom" in out.provider_errors[0][1]
    assert out.coverage == 0.5


async def test_dedupes_same_url_across_providers():
    out = await run_research("topic", providers=[OkProvider(), OverlappingProvider()])
    urls = [s.url for s in out.sources]
    assert len(urls) == len(set(urls))
    assert len(out.sources) == 2
