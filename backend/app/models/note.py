import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.core.encryption import EncryptedString


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PatientNote(SQLModel, table=True):
    """Patient-authored note at booking time (reason/symptoms). One per
    booking (data model: Booking 1:1 PatientNote). Encrypted at rest (F6)."""

    __tablename__ = "patient_notes"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    booking_id: uuid.UUID = Field(foreign_key="bookings.id", index=True, unique=True, nullable=False)
    patient_profile_id: uuid.UUID = Field(foreign_key="patient_profiles.id", index=True, nullable=False)

    content: str = Field(sa_type=EncryptedString)

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))


class ClinicalNote(SQLModel, table=True):
    """Doctor-authored clinical note, private by default. `is_shared_with_patient`
    is the per-note toggle a doctor flips to let the patient read it. One per
    booking (data model: Booking 1:1 ClinicalNote). Encrypted at rest (F6)."""

    __tablename__ = "clinical_notes"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    booking_id: uuid.UUID = Field(foreign_key="bookings.id", index=True, unique=True, nullable=False)
    doctor_id: uuid.UUID = Field(foreign_key="doctor_profiles.id", index=True, nullable=False)

    content: str = Field(sa_type=EncryptedString)
    is_shared_with_patient: bool = Field(default=False)

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
