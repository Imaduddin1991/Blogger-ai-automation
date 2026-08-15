"""Quality, policy, and repetition checks.

All checks are deterministic rules over the article text (no LLM cost):
structure/length quality signals, publisher-policy risk phrases (honest
warnings, never "guaranteed approval" promises), and repetition/originality
signals. Results are persisted as CheckResult rows by the orchestrator.
"""

from __future__ import annotations

import re
from collections import Counter

MIN_WORDS = 300
MIN_PARAGRAPHS = 3

# (regex, severity, message template). Matches are publisher-policy risk
# phrases: absolute claims, health/legal/financial advice, and hype words.
POLICY_PATTERNS: list[tuple[str, str, str]] = [
    (r"\bguarantee(?:d|s|ing)?\b", "warning", "Claim of a guarantee — publishers dislike absolute promises."),
    (r"\bcure[sd]?\b|\btreat[sd]?\s+cancer\b", "warning", "Health-cure language — medical claims need disclaimers and care."),
    (r"\b100%\s*(?:guaranteed|effective|safe)\b", "warning", "Absolute percentage claim — risky for publisher policy."),
    (r"\bbest\s+(?:ever|in the world)\b|\bworld['']?s\s+best\b", "info", "Superlative — tone it down unless proven."),
    (r"\bmoney[- ]back\s+guarantee\b", "error", "Money-back guarantee claim is a financial promise."),
    (r"\bzero[- ]?risk\b|\brisk[- ]?free\b", "warning", "Absolute risk claim — rare in reality; soften it."),
    (r"\bproven\s+to\b", "info", "'Proven to' is an unsupported certainty — attribute it."),
    (r"\bmiracle\b|\bsecret\s+doctors\b|\bclickbait\b", "info", "Sensationalist phrasing detected."),
    (r"\binvest(?:ing|ment)?\s+(?:tips?|advice)\b|\bget\s+rich\b", "warning", "Financial-advice framing — high publisher risk."),
]


def _text_without_markdown(body: str) -> str:
    return re.sub(r"[#>*_`\[\]()!]", " ", body or "")


def _paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip()]


def quality_checks(body: str) -> list[dict]:
    checks: list[dict] = []
    text = _text_without_markdown(body)
    word_count = len([w for w in text.split() if w])
    paragraphs = _paragraphs(body)
    headings = [l for l in (body or "").splitlines() if re.match(r"^#{1,6}\s+\S+", l.strip())]

    checks.append(
        {
            "check_type": "quality",
            "passed": word_count >= MIN_WORDS,
            "severity": "warning" if word_count < MIN_WORDS else "info",
            "message": f"Article length is {word_count} words ({MIN_WORDS}+ recommended).",
            "details": {"word_count": word_count},
        }
    )
    checks.append(
        {
            "check_type": "quality",
            "passed": len(paragraphs) >= MIN_PARAGRAPHS,
            "severity": "warning" if len(paragraphs) < MIN_PARAGRAPHS else "info",
            "message": f"Article has {len(paragraphs)} paragraphs ({MIN_PARAGRAPHS}+ recommended).",
            "details": {"paragraph_count": len(paragraphs)},
        }
    )
    checks.append(
        {
            "check_type": "quality",
            "passed": len(headings) >= 2,
            "severity": "warning" if len(headings) < 2 else "info",
            "message": f"Article has {len(headings)} headings (structure aids readability).",
            "details": {"heading_count": len(headings)},
        }
    )
    return checks


def policy_checks(body: str) -> list[dict]:
    checks: list[dict] = []
    text = _text_without_markdown(body).lower()
    for pattern, severity, message in POLICY_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            checks.append(
                {
                    "check_type": "policy",
                    "passed": False,
                    "severity": severity,
                    "message": message,
                    "details": {"phrase": pattern, "count": len(matches)},
                }
            )
    if not checks:
        checks.append(
            {
                "check_type": "policy",
                "passed": True,
                "severity": "info",
                "message": "No high-risk policy phrases detected.",
                "details": {},
            }
        )
    return checks


def _normalize_sentence(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def repetition_checks(body: str) -> list[dict]:
    checks: list[dict] = []
    text = _text_without_markdown(body)
    sentences = [_normalize_sentence(s) for s in re.split(r"[.!?]+", text) if len(s.split()) > 4]
    dupes = [s for s, c in Counter(sentences).items() if c > 1]
    checks.append(
        {
            "check_type": "repetition",
            "passed": not dupes,
            "severity": "warning" if dupes else "info",
            "message": f"Found {len(dupes)} repeated sentence(s)."
            if dupes
            else "No repeated sentences detected.",
            "details": {"repeated": dupes[:5]},
        }
    )

    words = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text)]
    overused = [(w, c) for w, c in Counter(words).most_common(3) if c >= 5]
    checks.append(
        {
            "check_type": "repetition",
            "passed": not overused,
            "severity": "warning" if overused else "info",
            "message": "No overused words detected."
            if not overused
            else "Some words appear frequently; consider synonyms.",
            "details": {"overused": dict(overused)},
        }
    )

    headings = [h.strip() for h in (body or "").splitlines() if re.match(r"^#{1,6}\s+\S+", h.strip())]
    heading_dupes = [h for h, c in Counter(headings).items() if c > 1]
    checks.append(
        {
            "check_type": "repetition",
            "passed": not heading_dupes,
            "severity": "warning" if heading_dupes else "info",
            "message": f"Duplicate heading(s): {', '.join(heading_dupes)}."
            if heading_dupes
            else "No duplicate headings detected.",
            "details": {"duplicate_heads": heading_dupes[:5]},
        }
    )
    return checks


def run_all_checks(
    body: str,
    *,
    title: str = "",
    seo_title: str | None = None,
    meta_description: str | None = None,
    slug: str | None = None,
    topic: str = "",
    target_word_count: int | None = None,
) -> list[dict]:
    """Run every check suite; returns one flat list of check dicts."""
    from pipeline.seo import DEFAULT_TARGET_WORD_COUNT, seo_checks

    checks: list[dict] = []
    checks += seo_checks(
        title,
        seo_title or title,
        meta_description or "",
        slug or "",
        body,
        topic,
        target_word_count=target_word_count or DEFAULT_TARGET_WORD_COUNT,
    )
    checks += quality_checks(body)
    checks += policy_checks(body)
    checks += repetition_checks(body)
    return checks
