import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import ReviewModerationStatus, enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Review(SQLModel, table=True):
    """One review per `completed` booking (F11). `no_show`/`cancelled` bookings
    cannot review — enforced in review_service, not here. Doctor may reply
    once; admin moderates before a review is publicly visible."""

    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    booking_id: uuid.UUID = Field(foreign_key="bookings.id", index=True, unique=True, nullable=False)
    patient_profile_id: uuid.UUID = Field(foreign_key="patient_profiles.id", index=True, nullable=False)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)

    rating: int
    comment: str | None = Field(default=None, max_length=2000)

    moderation_status: ReviewModerationStatus = Field(
        sa_column=enum_column(
            ReviewModerationStatus, nullable=False, index=True, default=ReviewModerationStatus.PENDING.value
        )
    )
    moderation_reason: str | None = None

    doctor_reply: str | None = Field(default=None, max_length=2000)
    doctor_replied_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
