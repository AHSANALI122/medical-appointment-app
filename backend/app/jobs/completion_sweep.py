"""Auto-completes `confirmed` bookings 24h after their appointment end time,
unless a doctor already marked them `no_show` or completed them early
(state-machine legal-transition guard makes that impossible to double-fire —
this sweep only ever sees bookings still in `confirmed`). Part of F5's
completion trigger; scheduled alongside the F12 reminder/expiry sweeps.
"""

from datetime import timedelta

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.services.state_machine import BookingStateMachine

logger = get_logger(__name__)

AUTO_COMPLETE_DELAY = timedelta(hours=24)


def sweep_completed_bookings(session: Session) -> int:
    cutoff = now_utc() - AUTO_COMPLETE_DELAY
    candidates = session.exec(
        select(Booking).where(Booking.status == BookingStatus.CONFIRMED, Booking.end_time_utc < cutoff)
    ).all()

    machine = BookingStateMachine(session)
    count = 0
    for booking in candidates:
        machine.mark_completed(booking)
        count += 1
        logger.info("booking.auto_completed", booking_id=str(booking.id))

    return count
