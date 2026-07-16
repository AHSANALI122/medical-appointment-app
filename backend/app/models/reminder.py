import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.models.enums import enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReminderOffset(StrEnum):
    T_24H = "24h"
    T_1H = "1h"


class ReminderLog(SQLModel, table=True):
    """Records a reminder that has already been sent for (booking, offset),
    so the sweep job (F12) is idempotent across restarts and repeated runs —
    the same pattern as the F3/F18 unique-constraint approach to correctness,
    just applied to 'has this fired yet' instead of 'is this slot free'."""

    __tablename__ = "reminder_logs"
    __table_args__ = (UniqueConstraint("booking_id", "offset", name="uq_reminder_logs_booking_offset"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    booking_id: uuid.UUID = Field(foreign_key="bookings.id", index=True, nullable=False)
    offset: ReminderOffset = Field(sa_column=enum_column(ReminderOffset, nullable=False, index=True))
    sent_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
