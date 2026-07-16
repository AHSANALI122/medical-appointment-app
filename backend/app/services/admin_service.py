"""F14 — Admin Dashboard: PMC verification queue, booking oversight, review
moderation (delegated to review_service), and platform stats. Every function
here assumes the caller already passed the `require_admin` dependency —
there is no additional authorization logic in this module.
"""

import uuid

from sqlmodel import Session, func, select

from app.core.exceptions import NotFoundError, PolicyViolationError
from app.models.booking import Booking
from app.models.doctor import DoctorProfile
from app.models.enums import BookingStatus, DoctorVerificationStatus, ReviewModerationStatus, UserRole
from app.models.review import Review
from app.models.user import User
from app.services import notification_service
from app.services.state_machine import BookingStateMachine


def list_pending_doctors(session: Session, *, offset: int, limit: int) -> tuple[list[DoctorProfile], int]:
    query = select(DoctorProfile).where(DoctorProfile.verification_status == DoctorVerificationStatus.UNVERIFIED)
    total = session.exec(select(func.count()).select_from(query.with_only_columns(DoctorProfile.id).subquery())).one()
    query = query.order_by(DoctorProfile.created_at.asc()).offset(offset).limit(limit)
    return list(session.exec(query).all()), total


def verify_doctor(
    session: Session, *, doctor_id: uuid.UUID, status: DoctorVerificationStatus, reason: str | None
) -> DoctorProfile:
    doctor = session.get(DoctorProfile, doctor_id)
    if doctor is None:
        raise NotFoundError("doctor not found")
    if status not in (DoctorVerificationStatus.VERIFIED, DoctorVerificationStatus.REJECTED):
        raise PolicyViolationError("verification status must be 'verified' or 'rejected'")

    doctor.verification_status = status
    doctor.verification_reason = reason
    session.add(doctor)
    session.commit()
    session.refresh(doctor)

    doctor_user = session.get(User, doctor.user_id)
    if doctor_user is not None:
        title = "Verification approved" if status == DoctorVerificationStatus.VERIFIED else "Verification rejected"
        body = (
            "Your PMC verification was approved — you're now visible in search and can receive bookings."
            if status == DoctorVerificationStatus.VERIFIED
            else f"Your PMC verification was rejected: {reason or 'no reason given'}"
        )
        notification_service.notify_user(session, user_id=doctor_user.id, booking=None, title=title, body=body)

    return doctor


def list_bookings_for_oversight(
    session: Session,
    *,
    status: BookingStatus | None,
    doctor_id: uuid.UUID | None,
    offset: int,
    limit: int,
) -> tuple[list[Booking], int]:
    query = select(Booking)
    if status is not None:
        query = query.where(Booking.status == status)
    if doctor_id is not None:
        query = query.where(Booking.doctor_id == doctor_id)

    total = session.exec(select(func.count()).select_from(query.with_only_columns(Booking.id).subquery())).one()
    query = query.order_by(Booking.created_at.desc()).offset(offset).limit(limit)
    return list(session.exec(query).all()), total


def get_booking_detail(session: Session, *, booking_id: uuid.UUID) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFoundError("booking not found")
    return booking


def correct_booking_completion(session: Session, *, booking_id: uuid.UUID, target: BookingStatus) -> Booking:
    booking = get_booking_detail(session, booking_id=booking_id)
    machine = BookingStateMachine(session)
    return machine.correct_completion(booking, target=target)


def get_platform_stats(session: Session) -> dict:
    users_by_role = dict(session.exec(select(User.role, func.count()).group_by(User.role)).all())
    doctors_by_status = dict(
        session.exec(select(DoctorProfile.verification_status, func.count()).group_by(DoctorProfile.verification_status)).all()
    )
    bookings_by_status = dict(session.exec(select(Booking.status, func.count()).group_by(Booking.status)).all())
    pending_reviews = session.exec(
        select(func.count()).where(Review.moderation_status == ReviewModerationStatus.PENDING)
    ).one()
    approved_reviews = session.exec(
        select(func.count()).where(Review.moderation_status == ReviewModerationStatus.APPROVED)
    ).one()

    return {
        "patients": users_by_role.get(UserRole.PATIENT, 0),
        "doctors": users_by_role.get(UserRole.DOCTOR, 0),
        "doctors_unverified": doctors_by_status.get(DoctorVerificationStatus.UNVERIFIED, 0),
        "doctors_verified": doctors_by_status.get(DoctorVerificationStatus.VERIFIED, 0),
        "doctors_rejected": doctors_by_status.get(DoctorVerificationStatus.REJECTED, 0),
        "bookings_by_status": {k.value: v for k, v in bookings_by_status.items()},
        "pending_reviews": pending_reviews,
        "approved_reviews": approved_reviews,
    }
