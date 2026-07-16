"""F12 — Reminders at T-24h and T-1h before a `confirmed` appointment.

Polling-based (like the F3/F18 expiry sweep) rather than per-booking
scheduled jobs: every sweep tick, find bookings whose start time has just
crossed a reminder threshold and that don't have a ReminderLog row yet for
that (booking_id, offset) pair. This is what makes reminders idempotent
across restarts and repeated sweeps, and it's also why stale reminders never
fire — a cancelled or rescheduled booking simply stops matching
`status == confirmed` and drops out of the query, no explicit "revoke" step
needed.
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.reminder import ReminderLog, ReminderOffset
from app.models.user import PatientProfile
from app.services import notification_service

logger = get_logger(__name__)

# Must exceed the sweep interval (main.py runs this every 5 min) so a booking
# crossing the threshold between two ticks is never skipped.
CATCH_UP_WINDOW = timedelta(minutes=15)

_OFFSETS: dict[ReminderOffset, timedelta] = {
    ReminderOffset.T_24H: timedelta(hours=24),
    ReminderOffset.T_1H: timedelta(hours=1),
}


def _already_sent(session: Session, *, booking_id, offset: ReminderOffset) -> bool:
    return (
        session.exec(
            select(ReminderLog).where(ReminderLog.booking_id == booking_id, ReminderLog.offset == offset)
        ).first()
        is not None
    )


def send_due_reminders(session: Session) -> int:
    now = now_utc()
    sent_count = 0

    for offset, delta in _OFFSETS.items():
        upper = now + delta
        lower = upper - CATCH_UP_WINDOW
        candidates = session.exec(
            select(Booking).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_time_utc > lower,
                Booking.start_time_utc <= upper,
            )
        ).all()

        for booking in candidates:
            if _already_sent(session, booking_id=booking.id, offset=offset):
                continue

            log = ReminderLog(booking_id=booking.id, offset=offset)
            session.add(log)
            try:
                session.commit()
            except IntegrityError:
                # Another sweep tick (or process) already logged this one.
                session.rollback()
                continue

            patient_profile = session.get(PatientProfile, booking.patient_profile_id)
            if patient_profile is not None:
                label = "24 hours" if offset == ReminderOffset.T_24H else "1 hour"
                notification_service.notify_user(
                    session,
                    user_id=patient_profile.user_id,
                    booking=booking,
                    title="Appointment reminder",
                    body=(
                        f"Your appointment is in {label}, on "
                        f"{booking.start_time_utc.isoformat()} at {booking.address_snapshot}."
                    ),
                )
            sent_count += 1
            logger.info("reminder.sent", booking_id=str(booking.id), offset=offset.value)

    return sent_count
