"""State machine: valid transitions, blocked transitions, unknown states."""

import pytest

from pipeline.state import (
    APPROVED,
    CHECKED,
    DRAFT,
    IMAGES_SEARCHING,
    IMAGE_READY,
    PUBLISHED,
    READY_FOR_REVIEW,
    RESEARCHING,
    RESEARCHED,
    TransitionError,
    ALL_STATES,
    transition,
)


def test_valid_transition():
    assert transition(DRAFT, RESEARCHING) == RESEARCHING
    assert transition(RESEARCHING, RESEARCHED) == RESEARCHED


def test_blocked_transition_raises():
    with pytest.raises(TransitionError):
        transition(PUBLISHED, RESEARCHING)


def test_unknown_current_state_raises():
    with pytest.raises(TransitionError):
        transition("not_a_state", RESEARCHING)


def test_unknown_target_state_raises():
    with pytest.raises(TransitionError):
        transition(DRAFT, "not_a_state")


def test_published_is_terminal():
    with pytest.raises(TransitionError):
        transition(PUBLISHED, PUBLISHED)


def test_all_states_covered_by_transitions():
    from pipeline.state import TRANSITIONS

    for state in ALL_STATES:
        assert state in TRANSITIONS, f"{state} missing from transition map"


def test_checked_to_images_searching_to_image_ready():
    assert transition(CHECKED, IMAGES_SEARCHING) == IMAGES_SEARCHING
    assert transition(IMAGES_SEARCHING, IMAGE_READY) == IMAGE_READY


def test_images_searching_failure_returns_to_checked():
    assert transition(IMAGES_SEARCHING, CHECKED) == CHECKED


def test_image_ready_can_research():
    assert transition(IMAGE_READY, IMAGES_SEARCHING) == IMAGES_SEARCHING


def test_image_states_cannot_bypass_review_gate():
    """No image-state change may jump straight to approval."""
    with pytest.raises(TransitionError):
        transition(IMAGES_SEARCHING, APPROVED)
    with pytest.raises(TransitionError):
        transition(IMAGE_READY, APPROVED)


def test_review_gate_still_requires_ready_for_review():
    with pytest.raises(TransitionError):
        transition(IMAGES_SEARCHING, READY_FOR_REVIEW)
