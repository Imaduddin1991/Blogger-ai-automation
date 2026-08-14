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
