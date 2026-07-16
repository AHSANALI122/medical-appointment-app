"""F20 — waitlist. A full slot lets patients queue FIFO; on cancellation,
the next in line gets a 15-minute exclusive hold — a system-created `draft`
booking (`source=system_waitlist`), reusing the existing unique-constraint
machinery on `bookings` instead of a parallel locking system, per spec.md.

Deliberately imports `booking_service` lazily inside `promote_next_in_line`
(not at module load time): `booking_service`'s cancellation paths call back
into this module to trigger promotion, so a module-level import here would
be circular.
"""

import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.core.exceptions import MedBookError, NotFoundError, PolicyViolationError
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import SLOT_HOLDING_STATUSES, BookingSource, WaitlistStatus
from app.models.user import PatientProfile
from app.models.waitlist import Waitlist
from app.services import notification_service
from app.services.state_machine import WAITLIST_HOLD_TTL


def join_waitlist(
    session: Session,
    *,
    patient_profile: PatientProfile,
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID,
    start_time_utc: datetime,
    end_time_utc: datetime,
) -> Waitlist:
    slot_is_held = session.exec(
        select(Booking).where(
            Booking.doctor_id == doctor_id,
            Booking.clinic_location_id == clinic_location_id,
            Booking.start_time_utc == start_time_utc,
            Booking.status.in_(SLOT_HOLDING_STATUSES),
        )
    ).first()
    if slot_is_held is None:
        raise PolicyViolationError("this slot is currently open — book it directly instead of joining the waitlist")

    existing = session.exec(
        select(Waitlist).where(
            Waitlist.doctor_id == doctor_id,
            Waitlist.clinic_location_id == clinic_location_id,
            Waitlist.start_time_utc == start_time_utc,
            Waitlist.patient_profile_id == patient_profile.id,
            Waitlist.status == WaitlistStatus.WAITING,
        )
    ).first()
    if existing is not None:
        return existing

    current_max = session.exec(
        select(Waitlist.position)
        .where(
            Waitlist.doctor_id == doctor_id,
            Waitlist.clinic_location_id == clinic_location_id,
            Waitlist.start_time_utc == start_time_utc,
        )
        .order_by(Waitlist.position.desc())
    ).first()
    next_position = (current_max or 0) + 1

    entry = Waitlist(
        doctor_id=doctor_id,
        clinic_location_id=clinic_location_id,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        patient_profile_id=patient_profile.id,
        position=next_position,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def leave_waitlist(session: Session, *, patient_profile: PatientProfile, waitlist_id: uuid.UUID) -> Waitlist:
    entry = session.get(Waitlist, waitlist_id)
    if entry is None or entry.patient_profile_id != patient_profile.id:
        raise NotFoundError("waitlist entry not found")
    if entry.status != WaitlistStatus.WAITING:
        raise PolicyViolationError("only a waiting entry can be left voluntarily")

    entry.status = WaitlistStatus.CANCELLED
    entry.updated_at = now_utc()
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_for_patient(session: Session, *, patient_profile: PatientProfile) -> list[Waitlist]:
    return list(
        session.exec(
            select(Waitlist)
            .where(Waitlist.patient_profile_id == patient_profile.id)
            .order_by(Waitlist.joined_at.desc())
        ).all()
    )


def mark_booked(session: Session, *, hold_booking_id: uuid.UUID) -> None:
    """Called when a waitlist hold's draft is confirmed by the patient
    (the same F18 HITL confirm path any draft goes through) — closes out
    the waitlist entry so it stops showing as active."""
    entry = session.exec(
        select(Waitlist).where(Waitlist.hold_booking_id == hold_booking_id, Waitlist.status == WaitlistStatus.HOLDING)
    ).first()
    if entry is None:
        return
    entry.status = WaitlistStatus.BOOKED
    entry.updated_at = now_utc()
    session.add(entry)
    session.commit()


def mark_expired(session: Session, *, hold_booking_id: uuid.UUID) -> Waitlist | None:
    entry = session.exec(
        select(Waitlist).where(Waitlist.hold_booking_id == hold_booking_id, Waitlist.status == WaitlistStatus.HOLDING)
    ).first()
    if entry is None:
        return None
    entry.status = WaitlistStatus.EXPIRED
    entry.updated_at = now_utc()
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def promote_next_in_line(
    session: Session,
    *,
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID,
    start_time_utc: datetime,
    end_time_utc: datetime,
) -> Waitlist | None:
    from app.services import booking_service  # deferred: avoids a circular import with booking_service

    candidates = session.exec(
        select(Waitlist)
        .where(
            Waitlist.doctor_id == doctor_id,
            Waitlist.clinic_location_id == clinic_location_id,
            Waitlist.start_time_utc == start_time_utc,
            Waitlist.status == WaitlistStatus.WAITING,
        )
        .order_by(Waitlist.position.asc())
    ).all()

    for entry in candidates:
        patient_profile = session.get(PatientProfile, entry.patient_profile_id)
        if patient_profile is None:
            continue

        try:
            hold = booking_service.create_draft_booking(
                session,
                patient_profile=patient_profile,
                doctor_id=doctor_id,
                clinic_location_id=clinic_location_id,
                start_time_utc=start_time_utc,
                end_time_utc=end_time_utc,
                source=BookingSource.SYSTEM_WAITLIST,
                ttl=WAITLIST_HOLD_TTL,
            )
        except MedBookError:
            # This candidate can't take the hold right now (e.g. the booking
            # window has since closed) — try the next person in line rather
            # than leaving the slot unclaimed.
            continue

        entry.status = WaitlistStatus.HOLDING
        entry.hold_booking_id = hold.id
        entry.updated_at = now_utc()
        session.add(entry)
        session.commit()
        session.refresh(entry)

        notification_service.notify_user(
            session,
            user_id=patient_profile.user_id,
            booking=hold,
            title="A slot opened up!",
            body="Your waitlist spot is ready — you have 15 minutes to confirm this appointment before it's offered to the next person.",
        )
        return entry

    return None
