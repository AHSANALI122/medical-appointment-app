import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    booking_id: uuid.UUID | None = Field(default=None, foreign_key="bookings.id", index=True)

    channel: NotificationChannel = Field(
        sa_column=enum_column(NotificationChannel, nullable=False, default=NotificationChannel.IN_APP.value)
    )
    status: NotificationStatus = Field(
        sa_column=enum_column(NotificationStatus, nullable=False, default=NotificationStatus.PENDING.value)
    )

    title: str
    body: str
    read_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))

    # F25: correlates an EMAIL row with the provider's bounce/delivery
    # webhook (Resend sends this back as `data.email_id`); FAILED rows carry
    # why, so the delivery report (per booking, per channel) is meaningful.
    provider_message_id: str | None = Field(default=None, index=True)
    failure_reason: str | None = None

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
