"""Dashboard endpoint: aggregate counts for the overview page."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import DashboardRead
from db.base import get_db
from db.models import Article, Idea, PublishJob, Research

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_local_token)])


def _count(db: Session, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


@router.get("", response_model=DashboardRead)
def dashboard(db: Session = Depends(get_db)) -> DashboardRead:
    return DashboardRead(
        idea_count=_count(db, Idea),
        research_count=_count(db, Research),
        article_count=_count(db, Article),
        publish_job_count=_count(db, PublishJob),
    )
