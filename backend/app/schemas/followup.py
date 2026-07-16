import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import FollowUpStatus
from app.services.followup_service import MAX_WEEKS, MIN_WEEKS


class FollowUpCreate(BaseModel):
    weeks: int = Field(ge=MIN_WEEKS, le=MAX_WEEKS)


class FollowUpRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_profile_id: uuid.UUID
    weeks: int
    target_date: date
    status: FollowUpStatus
    created_at: datetime
