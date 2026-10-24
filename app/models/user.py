from datetime import datetime

from pydantic import BaseModel


class UserProfile(BaseModel):
    id: str
    email: str | None = None
    full_name: str | None = None
    created_at: datetime
    updated_at: datetime
