"""Image row lifecycle statuses (Phase 4C).

Candidates persist as they arrive from a search; the human decides later.
`selected` is the only status that feeds the review gate; `rejected` rows are
kept with a visible `rejection_reason` so the UI can explain why.
"""

IMAGE_STATUS_CANDIDATE = "candidate"
IMAGE_STATUS_SUGGESTED = "suggested"
IMAGE_STATUS_SELECTED = "selected"
IMAGE_STATUS_REJECTED = "rejected"

IMAGE_STATUSES: frozenset[str] = frozenset(
    {
        IMAGE_STATUS_CANDIDATE,
        IMAGE_STATUS_SUGGESTED,
        IMAGE_STATUS_SELECTED,
        IMAGE_STATUS_REJECTED,
    }
)
