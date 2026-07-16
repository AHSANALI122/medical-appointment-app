import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PatientNoteWrite(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class PatientNoteRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    content: str
    created_at: datetime
    updated_at: datetime


class ClinicalNoteWrite(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    is_shared_with_patient: bool = False


class ClinicalNoteRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    content: str
    is_shared_with_patient: bool
    created_at: datetime
    updated_at: datetime
