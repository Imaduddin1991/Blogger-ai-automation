"""State machine: valid transitions, blocked transitions, unknown states."""

import pytest

from pipeline.state import (
    DRAFT,
    PUBLISHED,
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
