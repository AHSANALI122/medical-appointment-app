from enum import StrEnum
from typing import Any

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class DoctorVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class BookingStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    NO_SHOW = "no_show"


# Statuses that hold a slot and therefore participate in the partial UNIQUE constraint.
SLOT_HOLDING_STATUSES = (BookingStatus.DRAFT, BookingStatus.PENDING, BookingStatus.CONFIRMED)


class BookingSource(StrEnum):
    USER = "user"
    SYSTEM_WAITLIST = "system_waitlist"


class CancelledBy(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class ReviewModerationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    HOLDING = "holding"
    EXPIRED = "expired"
    BOOKED = "booked"
    CANCELLED = "cancelled"


class FollowUpStatus(StrEnum):
    SCHEDULED = "scheduled"
    NOTIFIED = "notified"
    DEFERRED = "deferred"


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


def enum_column(enum_cls: type[StrEnum], **column_kwargs: Any) -> Column:
    """Stores StrEnum columns by `.value` (e.g. 'draft') rather than
    SQLAlchemy's default `.name` (e.g. 'DRAFT') — the lowercase value is what
    the API serializes, what spec.md's state machine names, and what raw SQL
    predicates like the bookings partial UNIQUE index compare against."""
    return Column(
        SAEnum(enum_cls, values_callable=lambda cls: [e.value for e in cls], name=enum_cls.__name__.lower()),
        **column_kwargs,
    )
