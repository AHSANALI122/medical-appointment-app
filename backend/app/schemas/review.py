import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ReviewModerationStatus


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewReply(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)


class ReviewModerate(BaseModel):
    status: ReviewModerationStatus
    reason: str | None = Field(default=None, max_length=500)


class ReviewRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_profile_id: uuid.UUID
    rating: int
    comment: str | None = None
    moderation_status: ReviewModerationStatus
    moderation_reason: str | None = None
    doctor_reply: str | None = None
    doctor_replied_at: datetime | None = None
    created_at: datetime


class DoctorRatingSummary(BaseModel):
    average_rating: float | None = None
    review_count: int = 0
