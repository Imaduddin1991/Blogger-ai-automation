"""SEO stage: slug, fallback metadata, JSON parsing, rule checks."""

from pipeline.seo import (
    _seo_title_coherent,
    _truncate_with_ellipsis,
    build_slug,
    fallback_metadata,
    parse_seo_json,
    seo_checks,
)

GOOD_BODY = (
    "# Solar panels for beginners\n\n"
    + ("Solar panels convert sunlight into electricity using photovoltaic cells. " * 8)
    + "\n\n## How they work\n\n"
    + ("Photovoltaic cells release electrons when light strikes them, producing current. " * 8)
    + "\n\n## Costs and benefits\n\n"
    + ("Prices have fallen over the past decade, making solar a practical choice. " * 8)
)


def test_build_slug_basic_and_unicode():
    assert build_slug("Why Solar Panels Work!") == "why-solar-panels-work"
    assert build_slug("Café au lait") == "cafe-au-lait"
    assert build_slug("") == ""


def test_fallback_metadata_truncates():
    long_title = "Solar panels: " + ("Word " * 40)
    long_body = "## Intro\n\n" + "Word " * 60
    meta = fallback_metadata(long_title, long_body)
    assert len(meta.seo_title) <= 60
    assert len(meta.meta_description) <= 160
    assert "solar" in meta.labels


def test_fallback_metadata_uses_first_paragraph():
    meta = fallback_metadata("Solar panels", GOOD_BODY)
    assert meta.seo_title == "Solar panels"
    assert "convert sunlight" in meta.meta_description


def test_parse_seo_json_valid():
    fallback = fallback_metadata("Solar panels", GOOD_BODY)
    parsed = parse_seo_json(
        '{"seo_title": "Solar panels explained", "meta_description": "How PV works.", "labels": ["solar", "PV", "energy"]}',
        fallback,
    )
    assert parsed.seo_title == "Solar panels explained"
    assert parsed.labels == ["solar", "pv", "energy"]


def test_parse_seo_json_garbage_falls_back():
    fallback = fallback_metadata("Solar panels", GOOD_BODY)
    parsed = parse_seo_json("not json at all", fallback)
    assert parsed.seo_title == fallback.seo_title
    assert parsed.meta_description == fallback.meta_description


def test_truncate_with_ellipsis_never_mid_word():
    long_meta = "This is a sentence about solar panels. " * 10
    truncated = _truncate_with_ellipsis(long_meta, 100)
    assert len(truncated) <= 100
    assert truncated.endswith("…")
    assert truncated[:-1].endswith(".")  # cut on a sentence boundary, not mid-word


def test_truncate_with_ellipsis_keeps_short_text():
    assert _truncate_with_ellipsis("Short.", 160) == "Short."


def test_seo_title_coherent_flags_hallucinated_tail():
    ok, unknown = _seo_title_coherent(
        "Why Do Cats Purr?",
        "Why do cats purr?",
        "Why do cats purr?",
        GOOD_BODY,
    )
    assert ok is True
    ok, unknown = _seo_title_coherent(
        "Why Do Cats Purr? - Exploring the Mysteries of the Cat's Flu",
        "Why do cats purr?",
        "Why do cats purr?",
        GOOD_BODY,
    )
    assert ok is False
    assert "flu" in unknown


def test_seo_checks_flag_hallucinated_seo_title():
    checks = seo_checks(
        "Why do cats purr?",
        "Why Do Cats Purr? - Exploring the Mysteries of the Cat's Flu",
        "A short description about cats.",
        "why-do-cats-purr",
        GOOD_BODY,
        "Why do cats purr?",
        target_word_count=1000,
    )
    coherence = [c for c in checks if "not in the article" in (c["message"] or "")]
    assert len(coherence) == 1
    assert coherence[0]["passed"] is False


def test_seo_checks_pass_on_good_article():
    checks = seo_checks(
        "Solar panels for beginners",
        "Solar panels for beginners",
        "A short description about solar panels.",
        "solar-panels",
        GOOD_BODY,
        "solar panels",
        target_word_count=300,
    )
    by_msg = {c["message"].split(" ")[0]: c for c in checks}
    assert all(c["passed"] for c in checks if c["severity"] != "info")
    assert len(checks) == 11
    assert any(c["check_type"] == "seo" for c in checks)


def test_seo_checks_flag_long_title_and_short_body():
    checks = seo_checks(
        "No keyword here",
        "Z" * 80,
        "Z" * 200,
        "x" * 90,
        "## Only\n\nTiny body.",
        "solar panels",
        target_word_count=1000,
    )
    failed = {c["message"].split(" ")[0]: c for c in checks if not c["passed"]}
    assert "SEO" in failed  # title length
    assert "Meta" in failed  # description length
    assert "Word" in failed  # word count
    assert "Slug" in failed  # slug length
    assert "No" in failed or "The" in failed  # keyword checks
