"""Schedule endpoints: schedule articles for future publishing, cancel schedules."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import ScheduledArticleRead
from db.base import get_db
from db.models import Article, PublishJob
from pipeline.state import APPROVED, SCHEDULED, transition

router = APIRouter(prefix="/api", tags=["schedule"], dependencies=[Depends(require_local_token)])

# 30 days max schedule window (Blogger API limit)
_MAX_SCHEDULE_DAYS = 30


class ScheduleRequest(BaseModel):
    run_at: datetime = Field(description="ISO 8601 UTC datetime for when to publish")


@router.post("/articles/{article_id}/schedule", response_model=ScheduledArticleRead, status_code=201)
def schedule_article(article_id: int, body: ScheduleRequest, db: Session = Depends(get_db)):
    """Schedule an approved article for future publishing."""
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if article.status != APPROVED:
        raise HTTPException(
            status_code=409,
            detail=f"Article is '{article.status}', must be '{APPROVED}' to schedule",
        )

    now = datetime.now(timezone.utc)
    if body.run_at.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="run_at must be a timezone-aware UTC datetime",
        )
    if body.run_at <= now:
        raise HTTPException(
            status_code=400,
            detail="run_at must be in the future",
        )
    max_date = now + timedelta(days=_MAX_SCHEDULE_DAYS)
    if body.run_at > max_date:
        raise HTTPException(
            status_code=400,
            detail=f"run_at must be within {_MAX_SCHEDULE_DAYS} days",
        )

    # Cancel any existing pending job for this article
    existing = db.scalars(
        select(PublishJob)
        .where(PublishJob.article_id == article_id)
        .where(PublishJob.status == "pending")
    ).all()
    for job in existing:
        job.status = "cancelled"

    # Create the schedule job
    job = PublishJob(
        article_id=article_id,
        run_at=body.run_at,
        status="pending",
    )
    db.add(job)

    # Transition article state
    try:
        article.status = transition(article.status, SCHEDULED)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    db.commit()
    db.refresh(job)
    db.refresh(article)

    return ScheduledArticleRead(
        article_id=article.id,
        article_title=article.title,
        run_at=job.run_at,
        status="pending",
        job_id=job.id,
    )


@router.delete("/articles/{article_id}/schedule", status_code=200)
def cancel_schedule(article_id: int, db: Session = Depends(get_db)):
    """Cancel a scheduled article, returning it to APPROVED."""
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if article.status != SCHEDULED:
        raise HTTPException(
            status_code=409,
            detail=f"Article is '{article.status}', must be '{SCHEDULED}' to cancel schedule",
        )

    # Cancel all pending jobs for this article
    pending_jobs = list(
        db.scalars(
            select(PublishJob)
            .where(PublishJob.article_id == article_id)
            .where(PublishJob.status == "pending")
        ).all()
    )
    if not pending_jobs:
        raise HTTPException(
            status_code=404,
            detail="No pending schedule found for this article",
        )

    for job in pending_jobs:
        job.status = "cancelled"

    # Transition article back to APPROVED
    try:
        article.status = transition(article.status, APPROVED)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    db.commit()
    return {"ok": True, "article_id": article_id}


@router.get("/scheduled", response_model=list[ScheduledArticleRead])
def list_scheduled(db: Session = Depends(get_db)):
    """Return all scheduled articles with their run times."""
    jobs = list(
        db.scalars(
            select(PublishJob)
            .where(PublishJob.status == "pending")
            .order_by(PublishJob.run_at.asc())
        ).all()
    )
    if not jobs:
        return []

    # Batch-fetch articles
    article_ids = {j.article_id for j in jobs if j.article_id is not None}
    articles = {}
    if article_ids:
        for art in db.scalars(select(Article).where(Article.id.in_(article_ids))).all():
            articles[art.id] = art

    result = []
    for job in jobs:
        article = articles.get(job.article_id)
        result.append(ScheduledArticleRead(
            article_id=job.article_id,
            article_title=article.title if article else None,
            run_at=job.run_at,
            status=job.status,
            job_id=job.id,
        ))
    return result
