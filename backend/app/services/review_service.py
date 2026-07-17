"""F11 — Reviews & Ratings.

One review per `completed` booking, within 30 days of completion. Reviews
start `pending` and only appear publicly (and count toward a doctor's
aggregate rating) once an admin moderates them to `approved`. Doctor may
reply once per review.
"""

import uuid
from datetime import timedelta

from sqlmodel import Session, func, select

from app.core.exceptions import ForbiddenError, NotFoundError, PolicyViolationError
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import BookingStatus, ReviewModerationStatus
from app.models.review import Review
from app.models.user import PatientProfile

REVIEW_WINDOW = timedelta(days=30)


def _get_owned_booking(session: Session, booking_id: uuid.UUID, patient_profile: PatientProfile) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None or booking.patient_profile_id != patient_profile.id:
        raise NotFoundError("booking not found")
    return booking


def create_review(
    session: Session,
    *,
    booking_id: uuid.UUID,
    patient_profile: PatientProfile,
    rating: int,
    comment: str | None,
) -> Review:
    booking = _get_owned_booking(session, booking_id, patient_profile)

    if booking.status != BookingStatus.COMPLETED:
        raise ForbiddenError("only completed bookings can be reviewed")

    if booking.completed_at is not None and now_utc() > booking.completed_at + REVIEW_WINDOW:
        raise PolicyViolationError("the 30-day review window for this booking has passed")

    existing = session.exec(select(Review).where(Review.booking_id == booking_id)).first()
    if existing is not None:
        raise PolicyViolationError("this booking has already been reviewed")

    review = Review(
        booking_id=booking_id,
        patient_profile_id=patient_profile.id,
        doctor_id=booking.doctor_id,
        rating=rating,
        comment=comment,
        moderation_status=ReviewModerationStatus.PENDING,
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def get_review_for_booking_owner(
    session: Session, *, booking_id: uuid.UUID, patient_profile: PatientProfile
) -> Review | None:
    _get_owned_booking(session, booking_id, patient_profile)
    return session.exec(select(Review).where(Review.booking_id == booking_id)).first()


def doctor_reply_to_review(session: Session, *, review_id: uuid.UUID, doctor_id: uuid.UUID, reply: str) -> Review:
    review = session.get(Review, review_id)
    if review is None or review.doctor_id != doctor_id:
        raise NotFoundError("review not found")
    if review.doctor_reply is not None:
        raise PolicyViolationError("this review already has a reply")

    review.doctor_reply = reply
    review.doctor_replied_at = now_utc()
    review.updated_at = now_utc()
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def list_public_doctor_reviews(
    session: Session, *, doctor_id: uuid.UUID, offset: int, limit: int
) -> tuple[list[Review], int]:
    query = select(Review).where(
        Review.doctor_id == doctor_id, Review.moderation_status == ReviewModerationStatus.APPROVED
    )
    total = session.exec(select(func.count()).select_from(query.with_only_columns(Review.id).subquery())).one()
    query = query.order_by(Review.created_at.desc()).offset(offset).limit(limit)
    return list(session.exec(query).all()), total


def get_doctor_rating_summary(session: Session, *, doctor_id: uuid.UUID) -> tuple[float | None, int]:
    row = session.exec(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.doctor_id == doctor_id, Review.moderation_status == ReviewModerationStatus.APPROVED
        )
    ).one()
    avg_rating, count = row
    return (round(float(avg_rating), 2) if avg_rating is not None else None, count or 0)


def get_doctor_rating_summaries(
    session: Session, *, doctor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[float | None, int]]:
    """Batched form of `get_doctor_rating_summary` for list endpoints (F28
    N+1 prevention): one GROUP BY instead of a query per row. Doctors with
    no approved reviews are absent from the GROUP BY result, so callers get
    an explicit (None, 0) rather than a KeyError."""
    if not doctor_ids:
        return {}

    rows = session.exec(
        select(Review.doctor_id, func.avg(Review.rating), func.count(Review.id))
        .where(
            Review.doctor_id.in_(doctor_ids),
            Review.moderation_status == ReviewModerationStatus.APPROVED,
        )
        .group_by(Review.doctor_id)
    ).all()

    summaries = {
        doctor_id: (round(float(avg), 2) if avg is not None else None, count or 0)
        for doctor_id, avg, count in rows
    }
    return {doctor_id: summaries.get(doctor_id, (None, 0)) for doctor_id in doctor_ids}


# ---- admin moderation (routes wired in F14's admin router) ----------------


def list_pending_reviews(session: Session, *, offset: int, limit: int) -> tuple[list[Review], int]:
    query = select(Review).where(Review.moderation_status == ReviewModerationStatus.PENDING)
    total = session.exec(select(func.count()).select_from(query.with_only_columns(Review.id).subquery())).one()
    query = query.order_by(Review.created_at.asc()).offset(offset).limit(limit)
    return list(session.exec(query).all()), total


def moderate_review(
    session: Session, *, review_id: uuid.UUID, status: ReviewModerationStatus, reason: str | None
) -> Review:
    review = session.get(Review, review_id)
    if review is None:
        raise NotFoundError("review not found")

    review.moderation_status = status
    review.moderation_reason = reason
    review.updated_at = now_utc()
    session.add(review)
    session.commit()
    session.refresh(review)
    return review
