"""Publish log endpoints: history of publish attempts with status and details."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import PublishLogEntry
from db.base import get_db
from db.models import Article, PublishJob, PublishLog

router = APIRouter(prefix="/api/publish-log", tags=["publish-log"], dependencies=[Depends(require_local_token)])


def _enrich_log(log: PublishLog, article: Article | None) -> PublishLogEntry:
    """Build a PublishLogEntry, pulling article title and Blogger URL from the article."""
    return PublishLogEntry(
        id=log.id,
        article_id=log.article_id,
        article_title=article.title if article else None,
        action=log.action,
        result=log.result,
        details=log.details,
        blogger_post_url=article.blogger_post_url if article else None,
        created_at=log.created_at,
    )


@router.get("", response_model=list[PublishLogEntry])
def list_publish_log(db: Session = Depends(get_db)) -> list[PublishLogEntry]:
    """Return all publish log entries, newest first, with article titles."""
    logs = list(
        db.scalars(select(PublishLog).order_by(PublishLog.created_at.desc())).all()
    )
    if not logs:
        return []

    article_ids = {log.article_id for log in logs if log.article_id is not None}
    articles = {}
    if article_ids:
        for art in db.scalars(select(Article).where(Article.id.in_(article_ids))).all():
            articles[art.id] = art

    return [_enrich_log(log, articles.get(log.article_id)) for log in logs]


@router.get("/article/{article_id}", response_model=list[PublishLogEntry])
def get_article_publish_log(article_id: int, db: Session = Depends(get_db)) -> list[PublishLogEntry]:
    """Return publish log entries for a specific article."""
    article = db.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    logs = list(
        db.scalars(
            select(PublishLog)
            .where(PublishLog.article_id == article_id)
            .order_by(PublishLog.created_at.desc())
        ).all()
    )
    return [_enrich_log(log, article) for log in logs]


@router.get("/jobs", response_model=list[dict])
def list_publish_jobs(db: Session = Depends(get_db)) -> list[dict]:
    """Return all publish jobs with article titles, newest first."""
    jobs = list(
        db.scalars(select(PublishJob).order_by(PublishJob.run_at.desc())).all()
    )
    if not jobs:
        return []

    article_ids = {job.article_id for job in jobs if job.article_id is not None}
    articles = {}
    if article_ids:
        for art in db.scalars(select(Article).where(Article.id.in_(article_ids))).all():
            articles[art.id] = art

    return [
        {
            "id": job.id,
            "article_id": job.article_id,
            "article_title": articles[job.article_id].title if job.article_id and job.article_id in articles else None,
            "run_at": job.run_at.isoformat(),
            "status": job.status,
            "error": job.error,
            "retry_count": job.retry_count,
            "published_at": job.published_at.isoformat() if job.published_at else None,
            "blogger_post_id": job.blogger_post_id,
        }
        for job in jobs
    ]
