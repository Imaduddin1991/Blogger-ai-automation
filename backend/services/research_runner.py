"""Background research runner: a single serial worker queue.

Single-user, concurrency = 1: one research job at a time, protecting Ollama
and RAM (the plan requires the pipeline to run serially). Runs in a daemon
thread so it works from any context (sync FastAPI endpoints run in the
threadpool, where there is no event loop). DB rows are the durable source
of truth: if the process restarts mid-run, a row stuck in `researching` is
resumed lazily on the next read (see `ensure_running`).
"""

from __future__ import annotations

import asyncio
import queue
import threading

from db.base import SessionLocal
from pipeline.research.service import research_topic, run_research_job

_q: queue.Queue[tuple[int, int]] = queue.Queue()
_pending: set[int] = set()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _worker() -> None:
    while True:
        research_id, limit = _q.get()
        try:
            asyncio.run(_run(research_id, limit))
        except Exception:
            # The job persists its own failures; never let the worker die.
            pass
        finally:
            with _lock:
                _pending.discard(research_id)
            _q.task_done()


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


def start_background_research(research_id: int, *, limit: int = 5) -> None:
    """Queue a research run. No-op if the same run is already queued/running."""
    global _thread
    with _lock:
        if research_id in _pending:
            return
        _pending.add(research_id)
        _q.put((research_id, limit))
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name="research-worker", daemon=True)
            _thread.start()


def is_running(research_id: int) -> bool:
    return research_id in _pending


def ensure_running(research_id: int, *, limit: int = 5) -> None:
    """Resume a stale in-flight run (e.g. after a restart)."""
    start_background_research(research_id, limit=limit)
