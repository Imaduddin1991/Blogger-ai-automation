"""Deterministic image relevance scoring (Phase 4C).

Reuses the research `compute_relevance` semantics — the fraction of query
terms present in the candidate title — but fixes a false-negative that
matters for images: the research matcher only stems words of ≥4 characters,
so "cats" scored 0.0 against "Cat on Windowsill" (3-letter "cat" never
matched). Images routinely have short single-word titles, so this module adds
conservative, exact morphological handling: simple plurals (+s, +es, y→ies)
and a 4-char stem prefix rule. Matching is deliberately narrow — no fuzzy
similarity, no synonym expansion — so irrelevant candidates cannot pass on
broad keyword overlap.
"""

from __future__ import annotations

import re

MIN_RELEVANCE = 0.2  # same floor as the research providers

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,}")


def _content_words(text: str) -> set[str]:
    """Significant alphanumeric words (≥3 chars), punctuation-insensitive."""
    return {w.lower() for w in _TOKEN_RE.findall(text or "")}


def _is_plural_pair(a: str, b: str) -> bool:
    """True for exact singular/plural pairs (cat/cats, box/boxes, story/stories)."""
    if len(a) < 3 or len(b) < 3 or a == b:
        return False
    if a == b + "s" or b == a + "s":
        return True
    if a == b + "es" or b == a + "es":
        return True
    if a.endswith("ies") and b == a[:-3] + "y":
        return True
    if b.endswith("ies") and a == b[:-3] + "y":
        return True
    return False


def _word_matches(a: str, b: str) -> bool:
    """True if two words are equal, share a ≥4-char stem, or are exact
    singular/plural forms. Conservative: nothing fuzzier is ever a match."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b[:4]) or b.startswith(a[:4])):
        return True
    return _is_plural_pair(a, b)


def compute_image_relevance(query: str, title: str, description: str | None) -> float:
    """Image candidate relevance (0..1), deterministic and cheap.

    The fraction of significant query words present (as a word, 4-char stem,
    or exact plural form) in the candidate title/description. An empty query
    is a neutral 0.5 (cannot judge), matching the research convention.
    """
    query_words = _content_words(query)
    if not query_words:
        return 0.5
    text_words = _content_words(f"{title} {description or ''}")
    if not text_words:
        return 0.0
    hits = sum(1 for qw in query_words if any(_word_matches(qw, w) for w in text_words))
    return round(hits / len(query_words), 2)
