import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PatientProfileCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    relationship_label: str = Field(min_length=1, max_length=50)
    date_of_birth: datetime | None = None


class PatientProfileRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    relationship_label: str
    date_of_birth: datetime | None = None
    is_active: bool
    created_at: datetime
