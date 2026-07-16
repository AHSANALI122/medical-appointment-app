"""TTL sweep for draft/pending bookings whose `expires_at` has passed.

Per CLAUDE.md rule 4, TTLs are DB columns, never in-memory-only scheduler
state — this sweep is the thing that actually enforces them, and it is safe
to run from anywhere (a request, a cron tick, a test) since it only acts on
rows already past their stamped deadline. Full APScheduler wiring lands in
F12; this function is the unit that job will call on a timer.
"""

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.user import PatientProfile
from app.services import notification_service
from app.services.state_machine import BookingStateMachine

logger = get_logger(__name__)


def sweep_expired_bookings(session: Session) -> int:
    now = now_utc()
    candidates = session.exec(
        select(Booking).where(
            Booking.status.in_((BookingStatus.DRAFT, BookingStatus.PENDING)),
            Booking.expires_at.is_not(None),
            Booking.expires_at < now,
        )
    ).all()

    machine = BookingStateMachine(session)
    expired_count = 0
    for booking in candidates:
        was_pending = booking.status == BookingStatus.PENDING
        machine.expire(booking)
        expired_count += 1
        logger.info("booking.expired", booking_id=str(booking.id), was_pending=was_pending)

        if was_pending:
            patient_profile = session.get(PatientProfile, booking.patient_profile_id)
            if patient_profile is not None:
                notification_service.notify_user(
                    session,
                    user_id=patient_profile.user_id,
                    booking=booking,
                    title="Booking request expired",
                    body="The doctor did not respond in time. Please try another slot or doctor.",
                )

    return expired_count
