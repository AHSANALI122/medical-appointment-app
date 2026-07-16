import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import WaitlistStatus, enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Waitlist(SQLModel, table=True):
    """F20 — FIFO waitlist for a full slot. `position` is assigned at join
    time (max existing + 1) and never renumbered; promotion always looks up
    the lowest `position` still `waiting` for a slot key. `hold_booking_id`
    points at the system-created draft (`source=system_waitlist`) that
    represents this entry's 15-minute exclusive hold once promoted — reusing
    the existing unique-constraint machinery on `bookings` instead of a
    parallel locking system, per spec.md."""

    __tablename__ = "waitlist_entries"
    __table_args__ = (
        # One active ("waiting") entry per profile per slot — same
        # idempotency-via-partial-unique-index pattern as the bookings table.
        UniqueConstraint(
            "doctor_id", "clinic_location_id", "start_time_utc", "patient_profile_id", "status",
            name="uq_waitlist_entries_slot_profile_status",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)
    clinic_location_id: uuid.UUID = Field(foreign_key="clinic_locations.id", index=True, nullable=False)
    start_time_utc: datetime = Field(sa_column=utc_datetime_column(nullable=False, index=True))
    end_time_utc: datetime = Field(sa_column=utc_datetime_column(nullable=False))

    patient_profile_id: uuid.UUID = Field(foreign_key="patient_profiles.id", index=True, nullable=False)
    position: int = Field(nullable=False)

    status: WaitlistStatus = Field(
        sa_column=enum_column(WaitlistStatus, nullable=False, index=True, default=WaitlistStatus.WAITING.value)
    )
    hold_booking_id: uuid.UUID | None = Field(default=None, foreign_key="bookings.id")

    joined_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
