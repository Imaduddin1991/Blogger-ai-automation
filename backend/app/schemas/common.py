"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IdeaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    prompt: str | None = Field(default=None, max_length=10000)


class IdeaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    prompt: str | None
    created_at: datetime
    updated_at: datetime


class SettingRead(BaseModel):
    key: str
    value: str | None


class SettingUpdate(BaseModel):
    value: str | None


class HealthRead(BaseModel):
    status: str
    app: str
    database: str
    ollama: dict


class SourceRead(BaseModel):
    provider: str
    title: str
    url: str
    snippet: str | None
    relevance: float
    license: str | None


class ResearchOutputRead(BaseModel):
    topic: str
    sources: list[SourceRead]
    provider_errors: list[dict]
    coverage: float


class ResearchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    idea_id: int | None
    topic: str | None
    topic_key: str
    summary_text: str | None
    status: str
    coverage: float | None
    providers_used: list[str]
    provider_errors: dict | None
    sources: list[SourceRead]
    created_at: datetime
    updated_at: datetime


class ResearchStartRead(BaseModel):
    id: int
    status: str
    cached: bool


class DashboardRead(BaseModel):
    idea_count: int
    research_count: int
    article_count: int
    publish_job_count: int
