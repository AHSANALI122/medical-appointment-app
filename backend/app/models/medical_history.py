import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.core.encryption import EncryptedString


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MedicalHistory(SQLModel, table=True):
    """F24 — per-PatientProfile medical history (allergies, medications,
    chronic conditions, blood group, surgeries).

    Append-only: every patient edit inserts a new row with `version`
    incremented rather than updating in place, so the version history is the
    table itself — no separate history table to keep in sync. The "current"
    record for a profile is the row with the highest `version`. Encrypted at
    rest (Fernet, same EncryptedString column type as notes/chat) and every
    read is logged to AuditLog (F15) by the service layer.
    """

    __tablename__ = "medical_histories"
    __table_args__ = (
        UniqueConstraint("patient_profile_id", "version", name="uq_medical_histories_profile_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    patient_profile_id: uuid.UUID = Field(foreign_key="patient_profiles.id", index=True, nullable=False)
    version: int = Field(nullable=False)

    blood_group: str | None = Field(default=None, sa_type=EncryptedString)
    allergies: str | None = Field(default=None, sa_type=EncryptedString)
    medications: str | None = Field(default=None, sa_type=EncryptedString)
    chronic_conditions: str | None = Field(default=None, sa_type=EncryptedString)
    surgeries: str | None = Field(default=None, sa_type=EncryptedString)

    # Whoever saved this version — the owning patient, or a family-account
    # user acting on a dependent profile they own.
    edited_by_user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
