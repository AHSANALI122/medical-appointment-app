"""F26 — booking funnel counters (draft -> pending -> confirmed conversion).

Counted from durable timestamps (`pending_at`, `confirmed_at`), not from
current status. Current status would be wrong in both directions: a
`completed` booking obviously reached confirmed, and an `expired` one may
have died at either draft or pending. Every booking is created as a draft,
so `reached_draft` is simply the row count.

System-created waitlist hold drafts (`source=system_waitlist`) are excluded
— they're a locking mechanism (spec.md F14/changelog item 11), not a
patient deciding to book, and counting them would dilute the conversion
rate the funnel exists to measure.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.booking import Booking
from app.models.enums import BookingSource


@dataclass(frozen=True)
class BookingFunnel:
    reached_draft: int
    reached_pending: int
    reached_confirmed: int
    draft_to_pending_rate: float
    pending_to_confirmed_rate: float
    draft_to_confirmed_rate: float


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def get_booking_funnel(session: Session, *, since: datetime | None = None) -> BookingFunnel:
    filters = [Booking.source == BookingSource.USER]
    if since is not None:
        filters.append(Booking.created_at >= since)

    reached_draft = session.exec(select(func.count()).select_from(Booking).where(*filters)).one()
    reached_pending = session.exec(
        select(func.count()).select_from(Booking).where(*filters, Booking.pending_at.is_not(None))
    ).one()
    reached_confirmed = session.exec(
        select(func.count()).select_from(Booking).where(*filters, Booking.confirmed_at.is_not(None))
    ).one()

    return BookingFunnel(
        reached_draft=reached_draft,
        reached_pending=reached_pending,
        reached_confirmed=reached_confirmed,
        draft_to_pending_rate=_rate(reached_pending, reached_draft),
        pending_to_confirmed_rate=_rate(reached_confirmed, reached_pending),
        draft_to_confirmed_rate=_rate(reached_confirmed, reached_draft),
    )
