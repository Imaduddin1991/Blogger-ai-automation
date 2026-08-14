"""Idea endpoints: create, list, and start research for a blog topic."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import IdeaCreate, IdeaRead, ResearchStartRead
from db.base import get_db
from db.models import Idea
from pipeline.research.service import STATUS_COMPLETE, create_research
from services.research_runner import start_background_research

router = APIRouter(prefix="/api/ideas", tags=["ideas"], dependencies=[Depends(require_local_token)])


@router.post("", response_model=IdeaRead, status_code=201)
def create_idea(payload: IdeaCreate, db: Session = Depends(get_db)) -> Idea:
    idea = Idea(title=payload.title.strip(), prompt=payload.prompt)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


@router.get("", response_model=list[IdeaRead])
def list_ideas(db: Session = Depends(get_db)) -> list[Idea]:
    return list(db.scalars(select(Idea).order_by(Idea.created_at.desc())).all())


@router.get("/{idea_id}", response_model=IdeaRead)
def get_idea(idea_id: int, db: Session = Depends(get_db)) -> Idea:
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.post("/{idea_id}/research", response_model=ResearchStartRead, status_code=201)
def start_research_for_idea(idea_id: int, db: Session = Depends(get_db)) -> ResearchStartRead:
    """Kick off research for an idea (or return a completed cache hit)."""
    idea = db.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    research = create_research(db, idea.id, idea.title)
    cached = research.status == STATUS_COMPLETE
    if not cached:
        start_background_research(research.id)
    return ResearchStartRead(id=research.id, status=research.status, cached=cached)
