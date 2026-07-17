import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import NotificationPreference, UserRole, enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(index=True, unique=True, nullable=False)
    password_hash: str
    role: UserRole = Field(sa_column=enum_column(UserRole, nullable=False, index=True))
    full_name: str
    phone: str | None = None
    # F25: 'sms_first' skips straight to SMS instead of waiting on an email
    # bounce; 'default' is the in-app -> email -> (SMS on bounce/failure) path.
    notification_preference: NotificationPreference = Field(
        sa_column=enum_column(
            NotificationPreference, nullable=False, default=NotificationPreference.DEFAULT.value
        )
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))


class PatientProfile(SQLModel, table=True):
    """A bookable identity under a User account (family-account aware).

    Every patient User gets a 'self' profile automatically at registration;
    additional profiles (e.g. for dependents) are added later via F20.
    Bookings reference patient_profile_id, never user_id, per the data model.
    """

    __tablename__ = "patient_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    relationship_label: str = Field(default="self")
    full_name: str
    date_of_birth: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))


class RefreshToken(SQLModel, table=True):
    """Server-side record of issued refresh tokens, enabling rotation + revocation."""

    __tablename__ = "refresh_tokens"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    jti: str = Field(index=True, unique=True, nullable=False)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    expires_at: datetime = Field(sa_column=utc_datetime_column(nullable=False))
    revoked_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    replaced_by_jti: str | None = None
    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
