"""Draft stage: prompt building, output parsing, generation with a fake client."""

import asyncio

from pipeline.draft import (
    ArticleDraft,
    build_draft_prompt,
    count_words,
    generate_draft,
    parse_draft,
)
from pipeline.research.providers.base import Source

SOURCES = [
    Source(provider="fake", title="Solar basics", url="https://example.com/a", snippet="PV cells make electricity"),
    Source(provider="fake", title="Solar costs", url="https://example.com/b", snippet="Prices fell over the decade"),
]


def test_parse_draft_strict_format():
    text = "TITLE: Why solar panels work\nBODY:\n# Why solar panels work\n\n## How it works\n\nShort body here."
    draft = parse_draft(text, fallback_title="Fallback")
    assert draft.title == "Why solar panels work"
    assert "Short body here." in draft.body_markdown
    assert "# Why solar panels work" not in draft.body_markdown  # stray H1 removed


def test_parse_draft_falls_back_when_markers_missing():
    draft = parse_draft("Just a body with no markers.", fallback_title="Fallback")
    assert draft.title == "Fallback"
    assert draft.body_markdown == "Just a body with no markers."


def test_parse_draft_empty_output_uses_fallback():
    draft = parse_draft("  ", fallback_title="Fallback")
    assert draft.title == "Fallback"
    assert draft.body_markdown == ""


def test_parse_draft_accepts_loose_casing():
    text = "title: Loose\nbody:\nContent here."
    draft = parse_draft(text, fallback_title="Fallback")
    assert draft.title == "Loose"
    assert draft.body_markdown == "Content here."


def test_count_words_ignores_markup():
    body = "## Heading\n\nA short **paragraph** with a [link](https://example.com)"
    assert count_words(body) == 8


def test_build_draft_prompt_includes_sources_and_notes():
    prompt = build_draft_prompt("Solar", "Summary!", SOURCES, notes="Be friendly")
    assert "Solar" in prompt
    assert "Summary!" in prompt
    assert "Be friendly" in prompt
    assert "https://example.com/a" in prompt
    assert len(prompt.splitlines()) > 8


class FakeClient:
    async def chat(self, messages, *, model=None, format=None, options=None, timeout=None):
        return (
            "TITLE: The complete guide to solar panels\nBODY:\n"
            "## Introduction\n\nSolar panels convert light into electricity. "
            "## Costs\n\nPrices have fallen over the last decade."
        )


async def test_generate_draft_returns_parsed_draft():
    draft = await generate_draft("Solar panels", "Summary", SOURCES, FakeClient())
    assert isinstance(draft, ArticleDraft)
    assert draft.title == "The complete guide to solar panels"
    assert draft.word_count > 10


async def test_generate_draft_passes_generation_options():
    seen = {}

    class CapturingClient:
        async def chat(self, messages, *, model=None, format=None, options=None, timeout=None):
            seen["options"] = options
            seen["timeout"] = timeout
            return "TITLE: T\nBODY:\nBody text here."

    await generate_draft("Solar", "Summary", SOURCES, CapturingClient())
    assert seen["options"]["temperature"] == 0.5
    assert seen["options"]["num_ctx"] == 8192
    assert seen["timeout"] == 600.0
