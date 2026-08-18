"""In-process APScheduler for scheduled publishing.

Polls every 30 seconds for PublishJob rows where run_at <= now and
status == "pending". Transitions the article to PUBLISHING and fires
the publish job via the serial runner.

Runs inside the FastAPI process. On startup, scans for past-due jobs
and fires them immediately (catch-up).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.base import SessionLocal
from db.models import Article, PublishJob
from pipeline.state import APPROVED, SCHEDULED, transition
from services.article_runner import start_background_publish

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    job_defaults={"coalesce": True, "max_instances": 1},
)


def _fire_due_jobs() -> None:
    """Scan for due PublishJob rows and fire them."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due_jobs = list(
            db.scalars(
                select(PublishJob)
                .where(PublishJob.status == "pending")
                .where(PublishJob.run_at <= now)
            ).all()
        )
        for job in due_jobs:
            _fire_job(db, job)
    except Exception:
        logger.exception("Scheduler scan failed")
    finally:
        db.close()


def _fire_job(db: Session, job: PublishJob) -> None:
    """Fire a single scheduled publish job."""
    article = db.get(Article, job.article_id)
    if article is None:
        logger.warning("Scheduled job %s: article %s not found, skipping", job.id, job.article_id)
        job.status = "error"
        job.error = "Article not found"
        db.commit()
        return

    if article.status not in (APPROVED, SCHEDULED):
        logger.info(
            "Scheduled job %s: article %s is '%s', expected '%s' or '%s', skipping",
            job.id, article.id, article.status, APPROVED, SCHEDULED,
        )
        job.status = "error"
        job.error = f"Article is '{article.status}', not schedulable"
        db.commit()
        return

    # Transition article to SCHEDULED if it's APPROVED
    if article.status == APPROVED:
        try:
            new_status = transition(article.status, SCHEDULED)
            article.status = new_status
            db.commit()
        except Exception:
            logger.exception("Failed to transition article %s to SCHEDULED", article.id)
            return

    # Mark the job as running
    job.status = "running"
    db.commit()

    # Fire the publish via the serial runner
    ok = start_background_publish(article.id)
    if not ok:
        logger.info("Scheduled job %s: publish already queued for article %s", job.id, article.id)
        job.status = "completed"
        db.commit()


def start_scheduler() -> None:
    """Start the APScheduler background scheduler."""
    scheduler.add_job(
        _fire_due_jobs,
        "interval",
        seconds=30,
        id="publish-scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")

    # Run once immediately on startup to catch past-due jobs
    try:
        _fire_due_jobs()
    except Exception:
        logger.exception("Initial scheduler scan failed")


def shutdown_scheduler() -> None:
    """Shut down the APScheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
