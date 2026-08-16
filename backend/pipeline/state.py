"""Article lifecycle state machine.

Central authority for valid transitions. Every stage persists to the DB
before moving on; re-running a stage returns to its parent state first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DRAFT = "draft"
RESEARCHING = "researching"
RESEARCHED = "researched"
DRAFTING = "drafting"
DRAFTED = "drafted"
SEO_DONE = "seo_done"
CHECKED = "checked"
IMAGE_READY = "image_ready"
READY_FOR_REVIEW = "ready_for_review"
APPROVED = "approved"
SCHEDULED = "scheduled"
PUBLISHING = "publishing"
PUBLISHED = "published"
PUBLISH_FAILED = "publish_failed"

ALL_STATES = {
    DRAFT, RESEARCHING, RESEARCHED, DRAFTING, DRAFTED, SEO_DONE, CHECKED,
    IMAGE_READY, READY_FOR_REVIEW, APPROVED, SCHEDULED, PUBLISHING, PUBLISHED,
    PUBLISH_FAILED,
}

# Valid (from -> to) transitions. Anything not listed is impossible and is
# rejected by transition().
TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {RESEARCHING, DRAFTING},          # legacy idea flow; article start
    RESEARCHING: {RESEARCHED, DRAFT},        # success, or re-run/cancel
    RESEARCHED: {DRAFTING, RESEARCHING},     # draft, or re-research
    DRAFTING: {DRAFTED, DRAFT},              # success, or fail -> retry
    DRAFTED: {SEO_DONE, DRAFTING},
    SEO_DONE: {CHECKED, DRAFTED},
    CHECKED: {IMAGE_READY, READY_FOR_REVIEW, DRAFTED},  # image step, approve, or back to edit
    IMAGE_READY: {READY_FOR_REVIEW, DRAFTED},
    READY_FOR_REVIEW: {APPROVED, DRAFTED},   # approve, or edit more
    APPROVED: {SCHEDULED, READY_FOR_REVIEW, PUBLISHING},
    SCHEDULED: {PUBLISHING, APPROVED},       # fire now, or reschedule
    PUBLISHING: {PUBLISHED, PUBLISH_FAILED, APPROVED},
    PUBLISH_FAILED: {PUBLISHING, SCHEDULED, APPROVED},
    PUBLISHED: set(),                        # terminal
}


@dataclass(frozen=True)
class TransitionError(Exception):
    from_state: str
    to_state: str
    reason: str = field(default="")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.from_state} -> {self.to_state} not allowed: {self.reason}"


def transition(current: str, target: str) -> str:
    """Validate a state transition; returns the new state or raises."""
    if current not in ALL_STATES:
        raise TransitionError(current, target, f"unknown current state {current!r}")
    if target not in ALL_STATES:
        raise TransitionError(current, target, f"unknown target state {target!r}")
    if target not in TRANSITIONS.get(current, set()):
        raise TransitionError(
            current, target, "transition not in the allowed map"
        )
    return target
