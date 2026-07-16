import uuid
from datetime import date, datetime, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import FollowUpStatus, enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FollowUp(SQLModel, table=True):
    """F20 — doctor sets 'follow up in N weeks' at completion.
    `target_date` beyond the 60-day booking horizon is `deferred`; a daily
    sweep job (jobs/followup_sweep.py) fires the notification once the date
    enters the horizon, so a '3 mahine baad aana' follow-up doesn't silently
    fail validation."""

    __tablename__ = "follow_ups"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    booking_id: uuid.UUID = Field(foreign_key="bookings.id", index=True, nullable=False)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)
    patient_profile_id: uuid.UUID = Field(foreign_key="patient_profiles.id", index=True, nullable=False)

    weeks: int = Field(nullable=False)
    target_date: date = Field(index=True, nullable=False)

    status: FollowUpStatus = Field(
        sa_column=enum_column(FollowUpStatus, nullable=False, index=True, default=FollowUpStatus.SCHEDULED.value)
    )

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
