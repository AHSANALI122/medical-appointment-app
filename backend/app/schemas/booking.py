import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import BookingSource, BookingStatus, CancelledBy


class CreateDraftRequest(BaseModel):
    doctor_id: uuid.UUID
    clinic_location_id: uuid.UUID
    start_time_utc: datetime
    end_time_utc: datetime


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class BookingRead(BaseModel):
    id: uuid.UUID
    patient_profile_id: uuid.UUID
    doctor_id: uuid.UUID
    clinic_location_id: uuid.UUID
    start_time_utc: datetime
    end_time_utc: datetime
    status: BookingStatus
    source: BookingSource
    fee_charged: int
    address_snapshot: str
    expires_at: datetime | None = None
    rescheduled_from_id: uuid.UUID | None = None
    cancelled_by: CancelledBy | None = None
    cancelled_reason: str | None = None
    rejected_reason: str | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class DoctorDashboardRead(BaseModel):
    today: list[BookingRead]
    upcoming: list[BookingRead]
    pending: list[BookingRead]
