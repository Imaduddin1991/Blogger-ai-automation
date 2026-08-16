"""Deterministic image query generation (Phase 4C).

The MVP image stage makes no LLM call (free quota + hardware constraints), so
queries are derived from data the pipeline already has: the article topic,
title words, the first few heading words, and the top research source titles.
Every output is bounded, deterministic, de-duplicated, and free of functional
stop words. Producing only 1-3 short queries keeps provider requests polite.
"""

from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,}")

# Functional words with ≥3 letters that carry no search signal. The tokenizer
# already drops 1-2 letter words; this list catches the rest.
STOPWORDS: frozenset[str] = frozenset(
    {
        "about", "also", "all", "any", "are", "been", "but", "can", "could",
        "for", "from", "had", "has", "have", "how", "into", "its", "just",
        "many", "more", "most", "not", "our", "some", "than", "that", "their",
        "them", "then", "there", "these", "they", "this", "those", "too",
        "very", "was", "were", "what", "when", "where", "which", "who", "why",
        "will", "with", "would", "your",
    }
)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _TOKEN_RE.findall(text or "")]


def _significant(text: str) -> list[str]:
    return [w for w in _words(text) if w not in STOPWORDS]


def generate_image_queries(
    topic: str,
    title: str = "",
    headings: tuple[str, ...] = (),
    research_terms: tuple[str, ...] = (),
    *,
    max_queries: int = 3,
    max_terms: int = 5,
) -> list[str]:
    """Build 1-3 deterministic search queries from existing article data.

    Term priority: topic words, title words, first three heading words, first
    three research source titles. Queries produced (deduplicated, bounded):
      1. the cleaned topic phrase (fallback: the title),
      2. the topic's own terms plus the strongest keyword,
      3. the strongest keyword alone.
    """
    raw_base = _WS_RE.sub(" ", (topic or "").strip()).strip()
    if not raw_base:
        raw_base = _WS_RE.sub(" ", (title or "").strip()).strip()
    base = " ".join(dict.fromkeys(raw_base.split())) if raw_base else ""

    stream: list[str] = []
    for text in (topic, title, *(headings or ())[:3], *(research_terms or ())[:3]):
        stream.extend(_significant(text))

    freq: dict[str, int] = {}
    order: list[str] = []
    for word in stream:
        if word not in freq:
            order.append(word)
            freq[word] = 0
        freq[word] += 1

    if not order and not base:
        return []
    if not order:
        return [base]

    strongest = max(order, key=lambda w: (freq[w], -order.index(w)))
    topic_words = [w for w in order if w in _significant(base)]
    combo = list(dict.fromkeys([*topic_words, strongest]))[:max_terms]

    queries = [base] if base else []
    if combo:
        queries.append(" ".join(combo))
    queries.append(strongest)

    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        key = _WS_RE.sub(" ", query).strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(query.strip())
    return result[:max_queries]
