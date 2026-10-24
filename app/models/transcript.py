from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TranscriptCreate(BaseModel):
    title: str | None = None
    content: str = Field(min_length=1)
    summary: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptUpdate(BaseModel):
    title: str | None = None
    content: str | None = Field(default=None, min_length=1)
    summary: str | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None


class Transcript(BaseModel):
    id: str
    user_id: str
    org_id: str | None = None
    document_id: str | None = None
    practice_area_id: str | None = None
    title: str | None = None
    content: str
    summary: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
