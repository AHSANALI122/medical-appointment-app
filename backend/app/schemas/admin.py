import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import BookingStatus, DoctorVerificationStatus


class DoctorVerifyRequest(BaseModel):
    status: DoctorVerificationStatus
    reason: str | None = Field(default=None, max_length=500)


class CompletionCorrectionRequest(BaseModel):
    target: BookingStatus


class PlatformStatsRead(BaseModel):
    patients: int
    doctors: int
    doctors_unverified: int
    doctors_verified: int
    doctors_rejected: int
    bookings_by_status: dict[str, int]
    pending_reviews: int
    approved_reviews: int


class FeatureFlagRead(BaseModel):
    key: str
    enabled: bool


class FeatureFlagUpdate(BaseModel):
    enabled: bool


class AccountRestoreRead(BaseModel):
    user_id: uuid.UUID
    email: str
    is_active: bool
    deleted_at: datetime | None


class DoctorVerificationQueueItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    pmc_number: str
    specialization_id: uuid.UUID
    verification_status: DoctorVerificationStatus
