"""Generic single serial job runner shared by the whole pipeline.

One queue, one daemon worker thread, concurrency = 1. Every pipeline stage
(research, article generation, publish) submits jobs here so the pipeline
never overlaps Ollama work (protects RAM/CPU on a small machine). Jobs are
identified by a string key; submitting an already-running key is a no-op.

Runs in a daemon thread so it works from any context: sync FastAPI endpoints
execute in a threadpool where there is no event loop, so each job uses its
own `asyncio.run` and a fresh DB session.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_q: queue.Queue[tuple[str, Callable[[], None]]] = queue.Queue()
_pending: set[str] = set()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _worker() -> None:
    while True:
        key, job = _q.get()
        try:
            job()
        except Exception:
            # Jobs persist their own failures, but never let the worker die or
            # fail silently — log the traceback so stuck jobs are traceable.
            logger.exception("Pipeline job %s raised", key)
        finally:
            with _lock:
                _pending.discard(key)
            _q.task_done()


def _ensure_thread() -> None:
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name="pipeline-worker", daemon=True)
            _thread.start()


def submit(key: str, job: Callable[[], None]) -> bool:
    """Queue a job under `key`. Returns False if `key` is already queued/running."""
    with _lock:
        if key in _pending:
            return False
        _pending.add(key)
        _q.put((key, job))
    _ensure_thread()
    return True


def is_running(key: str) -> bool:
    return key in _pending


def async_job(coro_fn: Callable[[], "asyncio.coroutines.Coroutine"]) -> Callable[[], None]:
    """Wrap an async callable so the worker can run it (each job gets its own loop)."""

    def _run() -> None:
        asyncio.run(coro_fn())

    return _run
