from datetime import datetime

from pydantic import BaseModel


class Document(BaseModel):
    id: str
    user_id: str
    org_id: str | None = None
    filename: str
    content_type: str
    size_bytes: int
    page_count: int | None = None
    char_count: int
    extraction: dict = {}
    # The law the document's own governing-law clause names (services/governing_law.py), if any.
    governing_law: dict | None = None
    created_at: datetime


class DocumentUploadResponse(Document):
    preview: str
