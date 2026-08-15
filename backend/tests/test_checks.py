"""Quality, policy, and repetition checks (deterministic rules)."""

from pipeline.checks import (
    policy_checks,
    quality_checks,
    repetition_checks,
    run_all_checks,
)

GOOD_BODY = (
    "## Introduction\n\n"
    + ("Solar panels convert sunlight into electricity and provide clean power for homes. " * 12)
    + "\n\n## How it works\n\n"
    + ("Photovoltaic cells release electrons when sunlight strikes them. " * 12)
    + "\n\n## Costs and benefits\n\n"
    + ("Prices have fallen over the past decade and solar keeps getting cheaper. " * 12)
)


def test_quality_checks_pass_on_structured_body():
    checks = quality_checks(GOOD_BODY)
    assert all(c["passed"] for c in checks)
    assert len(checks) == 3


def test_quality_checks_flag_short_body():
    checks = quality_checks("## Only\n\nTiny.")
    assert not checks[0]["passed"]
    assert not checks[1]["passed"]


def test_policy_checks_detect_risk_phrases():
    body = "This method is guaranteed to work and cures all diseases. Zero risk!"
    checks = policy_checks(body)
    failed = [c for c in checks if not c["passed"]]
    assert len(failed) >= 2
    assert all(c["check_type"] == "policy" for c in checks)


def test_policy_checks_clean_body_passes():
    checks = policy_checks("Solar panels are a clean energy option for many homes.")
    assert len(checks) == 1
    assert checks[0]["passed"] is True


def test_repetition_checks_detect_duplicate_sentences():
    body = (
        "Solar panels convert sunlight into electricity. "
        "Solar panels convert sunlight into electricity. "
        "\n\n## More\n\n"
        "The cost has fallen over the last decade."
    )
    checks = repetition_checks(body)
    assert any(not c["passed"] for c in checks)


def test_run_all_checks_combines_suites():
    checks = run_all_checks(
        GOOD_BODY,
        title="Solar panels for beginners",
        seo_title="Solar panels for beginners",
        meta_description="A short description about solar panels.",
        slug="solar-panels",
        topic="solar panels",
    )
    types = {c["check_type"] for c in checks}
    assert types == {"seo", "quality", "policy", "repetition"}
    assert len(checks) > 10
