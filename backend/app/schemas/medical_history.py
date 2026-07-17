import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MedicalHistoryWrite(BaseModel):
    blood_group: str | None = Field(default=None, max_length=10)
    allergies: str | None = Field(default=None, max_length=2000)
    medications: str | None = Field(default=None, max_length=2000)
    chronic_conditions: str | None = Field(default=None, max_length=2000)
    surgeries: str | None = Field(default=None, max_length=2000)


class MedicalHistoryRead(BaseModel):
    id: uuid.UUID
    patient_profile_id: uuid.UUID
    version: int
    blood_group: str | None
    allergies: str | None
    medications: str | None
    chronic_conditions: str | None
    surgeries: str | None
    edited_by_user_id: uuid.UUID
    created_at: datetime
