import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.core.exceptions import ForbiddenError, NotFoundError, PolicyViolationError
from app.core.timezone import now_utc, utc_to_local
from app.models.booking import Booking
from app.models.doctor import ClinicLocation, DoctorProfile
from app.models.enums import BookingSource, BookingStatus, CancelledBy, DoctorVerificationStatus
from app.models.user import PatientProfile, User
from app.services import notification_service
from app.services.slot_service import MAX_HORIZON, MIN_LEAD_TIME
from app.services.state_machine import BookingStateMachine


def _validate_booking_window(start_time_utc: datetime) -> None:
    now = now_utc()
    if start_time_utc < now + MIN_LEAD_TIME:
        raise PolicyViolationError("start time must be at least 30 minutes in the future")
    if start_time_utc > now + MAX_HORIZON:
        raise PolicyViolationError("start time must be within 60 days")


def create_draft_booking(
    session: Session,
    *,
    patient_profile: PatientProfile,
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID,
    start_time_utc: datetime,
    end_time_utc: datetime,
    source: BookingSource = BookingSource.USER,
) -> Booking:
    _validate_booking_window(start_time_utc)

    doctor = session.get(DoctorProfile, doctor_id)
    if doctor is None:
        raise NotFoundError("doctor not found")
    if doctor.verification_status != DoctorVerificationStatus.VERIFIED:
        raise ForbiddenError("this doctor is not accepting bookings")

    location = session.get(ClinicLocation, clinic_location_id)
    if location is None or location.doctor_id != doctor_id or not location.is_active:
        raise NotFoundError("clinic location not found for this doctor")

    # Fee + address snapshot taken HERE — the moment the patient sees the card (F7/F8).
    address_snapshot = f"{location.name}, {location.address}, {location.city}"

    machine = BookingStateMachine(session)
    return machine.create_draft(
        patient_profile_id=patient_profile.id,
        doctor_id=doctor_id,
        clinic_location_id=clinic_location_id,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        fee_charged=doctor.consultation_fee,
        address_snapshot=address_snapshot,
        source=source,
    )


def _get_owned_booking(session: Session, booking_id: uuid.UUID, patient_profile: PatientProfile) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None or booking.patient_profile_id != patient_profile.id:
        raise NotFoundError("booking not found")
    return booking


def _get_doctor_booking(session: Session, booking_id: uuid.UUID, doctor: DoctorProfile) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None or booking.doctor_id != doctor.id:
        raise NotFoundError("booking not found")
    return booking


def confirm_booking(session: Session, *, booking_id: uuid.UUID, patient_profile: PatientProfile) -> Booking:
    booking = _get_owned_booking(session, booking_id, patient_profile)
    machine = BookingStateMachine(session)
    booking = machine.confirm(booking)

    doctor = session.get(DoctorProfile, booking.doctor_id)
    if doctor is not None:
        doctor_user = session.get(User, doctor.user_id)
        if doctor_user is not None:
            notification_service.notify_user(
                session,
                user_id=doctor_user.id,
                booking=booking,
                title="New booking request",
                body=f"A patient requested an appointment on {booking.start_time_utc.isoformat()}.",
            )
    return booking


def doctor_accept_booking(session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile) -> Booking:
    booking = _get_doctor_booking(session, booking_id, doctor)
    machine = BookingStateMachine(session)
    booking = machine.doctor_accept(booking)
    # Confirmation notification carries the same fee + address the patient
    # saw at draft time (F7/F8) — never the doctor's current live values.
    _notify_patient(
        session,
        booking,
        title="Booking confirmed",
        body=(
            f"Your appointment on {booking.start_time_utc.isoformat()} is confirmed. "
            f"Fee: Rs. {booking.fee_charged}. Location: {booking.address_snapshot}."
        ),
    )
    return booking


def doctor_reject_booking(
    session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile, reason: str
) -> Booking:
    booking = _get_doctor_booking(session, booking_id, doctor)
    machine = BookingStateMachine(session)
    booking = machine.doctor_reject(booking, reason=reason)
    _notify_patient(
        session, booking, title="Booking rejected", body=f"Your appointment request was declined: {reason}"
    )
    return booking


def patient_cancel_booking(
    session: Session, *, booking_id: uuid.UUID, patient_profile: PatientProfile, reason: str
) -> Booking:
    booking = _get_owned_booking(session, booking_id, patient_profile)
    doctor = session.get(DoctorProfile, booking.doctor_id)
    if doctor is None:
        raise NotFoundError("doctor not found")

    machine = BookingStateMachine(session)
    booking = machine.cancel(
        booking,
        cancelled_by=CancelledBy.PATIENT,
        reason=reason,
        cancellation_policy_hours=doctor.cancellation_policy_hours,
    )

    doctor_user = session.get(User, doctor.user_id)
    if doctor_user is not None:
        notification_service.notify_user(
            session,
            user_id=doctor_user.id,
            booking=booking,
            title="Booking cancelled",
            body=f"The patient cancelled their appointment: {reason}",
        )
    return booking


def doctor_cancel_booking(
    session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile, reason: str
) -> Booking:
    booking = _get_doctor_booking(session, booking_id, doctor)
    machine = BookingStateMachine(session)
    booking = machine.cancel(
        booking,
        cancelled_by=CancelledBy.DOCTOR,
        reason=reason,
        cancellation_policy_hours=doctor.cancellation_policy_hours,
    )
    _notify_patient(
        session, booking, title="Booking cancelled by doctor", body=f"Reason: {reason}"
    )
    return booking


def doctor_mark_completed(session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile) -> Booking:
    """Doctor's early-complete override (F5) — the auto-complete sweep job
    (jobs/completion_sweep.py) handles the +24h-after-end default path."""
    booking = _get_doctor_booking(session, booking_id, doctor)
    machine = BookingStateMachine(session)
    return machine.mark_completed(booking)


def doctor_mark_no_show(session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile) -> Booking:
    booking = _get_doctor_booking(session, booking_id, doctor)
    machine = BookingStateMachine(session)
    return machine.mark_no_show(booking)


def _notify_patient(session: Session, booking: Booking, *, title: str, body: str) -> None:
    patient_profile = session.get(PatientProfile, booking.patient_profile_id)
    if patient_profile is None:
        return
    notification_service.notify_user(
        session, user_id=patient_profile.user_id, booking=booking, title=title, body=body
    )


def list_patient_bookings(
    session: Session, *, patient_profile: PatientProfile, status: BookingStatus | None = None
) -> list[Booking]:
    query = select(Booking).where(Booking.patient_profile_id == patient_profile.id)
    if status is not None:
        query = query.where(Booking.status == status)
    query = query.order_by(Booking.start_time_utc.desc())
    return list(session.exec(query).all())


def list_doctor_bookings(
    session: Session, *, doctor: DoctorProfile, status: BookingStatus | None = None
) -> list[Booking]:
    query = select(Booking).where(Booking.doctor_id == doctor.id)
    if status is not None:
        query = query.where(Booking.status == status)
    query = query.order_by(Booking.start_time_utc.desc())
    return list(session.exec(query).all())


def get_doctor_booking_or_403(session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile) -> Booking:
    """Row-level auth for the doctor booking-detail view (F13 acceptance):
    a booking that truly doesn't exist is 404, but a booking that exists and
    belongs to a *different* doctor is 403 — the explicit distinction the
    acceptance test checks for, unlike the note/accept endpoints which
    collapse both cases to 404 to avoid leaking existence."""
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFoundError("booking not found")
    if booking.doctor_id != doctor.id:
        raise ForbiddenError("this booking does not belong to you")
    return booking


def get_doctor_dashboard(session: Session, *, doctor: DoctorProfile) -> dict:
    """Today's schedule (Asia/Karachi calendar day), upcoming confirmed
    bookings beyond today, and pending acceptances (F13)."""
    today_local = utc_to_local(now_utc()).date()

    all_active = session.exec(
        select(Booking)
        .where(Booking.doctor_id == doctor.id, Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.PENDING)))
        .order_by(Booking.start_time_utc.asc())
    ).all()

    today: list[Booking] = []
    upcoming: list[Booking] = []
    pending: list[Booking] = []
    for booking in all_active:
        if booking.status == BookingStatus.PENDING:
            pending.append(booking)
            continue
        if utc_to_local(booking.start_time_utc).date() == today_local:
            today.append(booking)
        elif booking.start_time_utc > now_utc():
            upcoming.append(booking)

    return {"today": today, "upcoming": upcoming, "pending": pending}
