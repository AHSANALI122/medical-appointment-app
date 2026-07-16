import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import WaitlistStatus


class WaitlistJoinRequest(BaseModel):
    doctor_id: uuid.UUID
    clinic_location_id: uuid.UUID
    start_time_utc: datetime
    end_time_utc: datetime


class WaitlistRead(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    clinic_location_id: uuid.UUID
    start_time_utc: datetime
    end_time_utc: datetime
    position: int
    status: WaitlistStatus
    hold_booking_id: uuid.UUID | None = None
    joined_at: datetime
