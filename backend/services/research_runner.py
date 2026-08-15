"""Background research runner: submits jobs to the shared serial pipeline runner.

Research runs are serialized (concurrency = 1) so the pipeline never overlaps
Ollama work. Rows are the durable source of truth: if the process restarts
mid-run, a row stuck in `researching` is resumed lazily on the next read (see
`ensure_running`).
"""

from __future__ import annotations

from db.base import SessionLocal
from pipeline.research.service import research_topic, run_research_job
from services.runner import async_job, is_running as _runner_is_running, submit as _runner_submit


async def _run(research_id: int, limit: int) -> None:
    db = SessionLocal()
    try:
        from db.models import Research

        research = db.get(Research, research_id)
        if research is None:
            return
        await run_research_job(
            db, research, topic=research_topic(db, research_id), limit=limit
        )
    finally:
        db.close()


def _key(research_id: int) -> str:
    return f"research:{research_id}"


def start_background_research(research_id: int, *, limit: int = 5) -> None:
    """Queue a research run. No-op if the same run is already queued/running."""
    _runner_submit(_key(research_id), async_job(lambda: _run(research_id, limit)))


def is_running(research_id: int) -> bool:
    return _runner_is_running(_key(research_id))


def ensure_running(research_id: int, *, limit: int = 5) -> None:
    """Resume a stale in-flight run (e.g. after a restart)."""
    start_background_research(research_id, limit=limit)
