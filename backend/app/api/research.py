"""Research endpoints: list runs and read one run with sources + summary.

Reads resume a stale in-flight run (after a process restart) so a research
row is never stuck in `researching` permanently.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import require_local_token
from app.schemas.common import ResearchRead
from db.base import get_db
from db.models import Research
from pipeline.research.service import STATUS_RESEARCHING
from services.research_runner import ensure_running, is_running

router = APIRouter(prefix="/api/research", tags=["research"], dependencies=[Depends(require_local_token)])


def _get_with_sources(db: Session, research_id: int) -> Research:
    research = db.scalars(
        select(Research)
        .options(selectinload(Research.sources))
        .where(Research.id == research_id)
    ).first()
    if research is None:
        raise HTTPException(status_code=404, detail="Research not found")
    return research


@router.get("", response_model=list[ResearchRead])
def list_research(db: Session = Depends(get_db)) -> list[Research]:
    return list(
        db.scalars(
            select(Research)
            .options(selectinload(Research.sources))
            .order_by(Research.created_at.desc())
        ).all()
    )


@router.get("/{research_id}", response_model=ResearchRead)
def get_research(research_id: int, db: Session = Depends(get_db)) -> Research:
    research = _get_with_sources(db, research_id)
    if research.status == STATUS_RESEARCHING and not is_running(research_id):
        ensure_running(research_id)
    return research
