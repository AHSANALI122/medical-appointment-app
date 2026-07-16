"""F20 — doctor sets 'follow up in N weeks' at completion. If the target
date falls within the 60-day booking horizon right now, the suggestion
notification fires immediately; otherwise it's deferred until a daily sweep
job (jobs/followup_sweep.py) sees the target date enter the horizon —
otherwise every '3 mahine baad aana' follow-up would silently fail
validation, per spec.md.
"""

import uuid
from datetime import date, timedelta

from sqlmodel import Session, select

from app.core.exceptions import PolicyViolationError
from app.core.timezone import now_local
from app.models.doctor import DoctorProfile
from app.models.enums import BookingStatus, FollowUpStatus
from app.models.followup import FollowUp
from app.models.user import PatientProfile
from app.services import booking_service, notification_service, slot_service
from app.services.slot_service import MAX_HORIZON

MIN_WEEKS = 1
MAX_WEEKS = 52


def _within_horizon(target_date: date) -> bool:
    return target_date <= (now_local() + MAX_HORIZON).date()


def _notify_or_defer(session: Session, follow_up: FollowUp) -> None:
    if not _within_horizon(follow_up.target_date):
        follow_up.status = FollowUpStatus.DEFERRED
        session.add(follow_up)
        session.commit()
        return

    patient_profile = session.get(PatientProfile, follow_up.patient_profile_id)
    if patient_profile is not None:
        suggested = slot_service.next_available_slot_for_doctor(session, doctor_id=follow_up.doctor_id)
        body = f"Your doctor suggested a follow-up visit around {follow_up.target_date.isoformat()}."
        if suggested is not None:
            body += f" Next available slot: {suggested.isoformat()}."
        notification_service.notify_user(
            session, user_id=patient_profile.user_id, booking=None, title="Follow-up suggested", body=body
        )

    follow_up.status = FollowUpStatus.NOTIFIED
    session.add(follow_up)
    session.commit()


def schedule_follow_up(
    session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile, weeks: int
) -> FollowUp:
    booking = booking_service.get_doctor_booking_or_403(session, booking_id=booking_id, doctor=doctor)
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED):
        raise PolicyViolationError("follow-up can only be scheduled for a confirmed or completed visit")
    if not (MIN_WEEKS <= weeks <= MAX_WEEKS):
        raise PolicyViolationError(f"weeks must be between {MIN_WEEKS} and {MAX_WEEKS}")

    target_date = now_local().date() + timedelta(weeks=weeks)
    follow_up = FollowUp(
        booking_id=booking.id,
        doctor_id=doctor.id,
        patient_profile_id=booking.patient_profile_id,
        weeks=weeks,
        target_date=target_date,
    )
    session.add(follow_up)
    session.commit()
    session.refresh(follow_up)

    _notify_or_defer(session, follow_up)
    session.refresh(follow_up)
    return follow_up


def sweep_deferred_followups(session: Session) -> int:
    deferred = session.exec(select(FollowUp).where(FollowUp.status == FollowUpStatus.DEFERRED)).all()
    notified_count = 0
    for follow_up in deferred:
        if _within_horizon(follow_up.target_date):
            _notify_or_defer(session, follow_up)
            notified_count += 1
    return notified_count
