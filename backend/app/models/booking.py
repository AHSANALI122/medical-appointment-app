import uuid
from datetime import datetime, timezone

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import (
    SLOT_HOLDING_STATUSES,
    BookingSource,
    BookingStatus,
    CancelledBy,
    enum_column,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_slot_holding_values = ", ".join(f"'{s.value}'" for s in SLOT_HOLDING_STATUSES)


class Booking(SQLModel, table=True):
    __tablename__ = "bookings"
    __table_args__ = (
        # Slot-conflict prevention: a concurrent insert for the same doctor/location/time
        # while another booking already holds it (draft/pending/confirmed) loses cleanly
        # at the DB layer. No version columns, no advisory locks, no app-level check-then-insert.
        Index(
            "uq_bookings_active_slot",
            "doctor_id",
            "clinic_location_id",
            "start_time_utc",
            unique=True,
            postgresql_where=text(f"status IN ({_slot_holding_values})"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    patient_profile_id: uuid.UUID = Field(foreign_key="patient_profiles.id", index=True, nullable=False)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)
    clinic_location_id: uuid.UUID = Field(foreign_key="clinic_locations.id", index=True, nullable=False)

    start_time_utc: datetime = Field(sa_column=utc_datetime_column(nullable=False, index=True))
    end_time_utc: datetime = Field(sa_column=utc_datetime_column(nullable=False))

    status: BookingStatus = Field(
        sa_column=enum_column(BookingStatus, nullable=False, index=True, default=BookingStatus.DRAFT.value)
    )
    source: BookingSource = Field(
        sa_column=enum_column(BookingSource, nullable=False, default=BookingSource.USER.value)
    )

    # Snapshots — taken at draft creation, immutable from confirmed onward (F7/F8).
    fee_charged: int
    address_snapshot: str

    expires_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True, index=True))
    idempotency_key: str = Field(index=True, unique=True, nullable=False)

    rescheduled_from_id: uuid.UUID | None = Field(default=None, foreign_key="bookings.id")
    cancelled_by: CancelledBy | None = Field(default=None, sa_column=enum_column(CancelledBy, nullable=True))
    cancelled_reason: str | None = None
    rejected_reason: str | None = None

    confirmed_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    cancelled_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
