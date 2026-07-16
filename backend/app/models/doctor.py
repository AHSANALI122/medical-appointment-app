import uuid
from datetime import date, datetime, time, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import DoctorVerificationStatus, Weekday, enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DoctorProfile(SQLModel, table=True):
    __tablename__ = "doctor_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, unique=True, nullable=False)
    specialization_id: uuid.UUID = Field(foreign_key="specialization_taxonomy.id", index=True)

    qualifications: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    consultation_fee: int = Field(description="PKR, integer")

    pmc_number: str = Field(index=True)
    verification_status: DoctorVerificationStatus = Field(
        sa_column=enum_column(
            DoctorVerificationStatus,
            nullable=False,
            index=True,
            default=DoctorVerificationStatus.UNVERIFIED.value,
        )
    )
    verification_reason: str | None = None

    # Patient cancellation policy window for this doctor, in hours. Floor = 1h (spec F5).
    cancellation_policy_hours: int = Field(default=2)

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))


class ClinicLocation(SQLModel, table=True):
    __tablename__ = "clinic_locations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)
    name: str
    address: str
    city: str = Field(index=True)
    map_embed_url: str | None = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))


class AvailabilityRule(SQLModel, table=True):
    """Weekly recurring availability for a doctor at a specific clinic location."""

    __tablename__ = "availability_rules"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)
    clinic_location_id: uuid.UUID = Field(foreign_key="clinic_locations.id", index=True, nullable=False)

    weekday: Weekday = Field(sa_column=enum_column(Weekday, nullable=False))
    start_time_local: time = Field(description="Asia/Karachi local time")
    end_time_local: time = Field(description="Asia/Karachi local time")
    slot_duration_minutes: int = Field(default=30)
    is_active: bool = Field(default=True)


class AvailabilityException(SQLModel, table=True):
    """Leave / holiday override for a single date. When present for a
    (doctor, date[, location]), that date is excluded from slot generation."""

    __tablename__ = "availability_exceptions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)
    clinic_location_id: uuid.UUID | None = Field(
        default=None, foreign_key="clinic_locations.id", index=True
    )
    exception_date: date = Field(index=True, description="Asia/Karachi local date")
    reason: str | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
