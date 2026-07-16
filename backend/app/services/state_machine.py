"""The single source of truth for booking status transitions (CLAUDE.md rule 1).

No router or job may set `Booking.status` directly — every transition goes
through a method here, which validates the current state, applies the
canonical guard for that edge, and stamps the relevant timestamp. The legal
graph mirrors the Canonical Booking State Machine in spec.md exactly; no
feature may invent its own states or edges.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.exceptions import BookingConflictError, PolicyViolationError, SlotUnavailableError
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.doctor import DoctorProfile
from app.models.enums import BookingSource, BookingStatus, CancelledBy

DRAFT_TTL = timedelta(minutes=10)
WAITLIST_HOLD_TTL = timedelta(minutes=15)
PENDING_MAX_TTL = timedelta(hours=24)
PENDING_MIN_LEAD = timedelta(hours=2)
MAX_ACTIVE_DRAFTS_PER_PROFILE = 3

_LEGAL_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    # Per spec.md's canonical diagram, draft only ever resolves to pending
    # (patient tap) or expired (TTL) — there is no direct draft->cancelled
    # edge; abandoning a draft just means letting its 10-min TTL expire it.
    BookingStatus.DRAFT: {BookingStatus.PENDING, BookingStatus.EXPIRED},
    BookingStatus.PENDING: {
        BookingStatus.CONFIRMED,
        BookingStatus.REJECTED,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.CONFIRMED: {BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.NO_SHOW},
    BookingStatus.COMPLETED: {BookingStatus.NO_SHOW},
    BookingStatus.NO_SHOW: {BookingStatus.COMPLETED},
    BookingStatus.REJECTED: set(),
    BookingStatus.EXPIRED: set(),
    BookingStatus.CANCELLED: set(),
}


class IllegalTransitionError(PolicyViolationError):
    def __init__(self, current: BookingStatus, target: BookingStatus):
        super().__init__(f"cannot transition booking from {current.value!r} to {target.value!r}")


def _pending_ttl(start_time_utc: datetime) -> datetime:
    now = now_utc()
    by_max_wait = now + PENDING_MAX_TTL
    by_lead_time = start_time_utc - PENDING_MIN_LEAD
    return min(by_max_wait, by_lead_time)


class BookingStateMachine:
    def __init__(self, session: Session):
        self.session = session

    def _assert_legal(self, booking: Booking, target: BookingStatus) -> None:
        if target not in _LEGAL_TRANSITIONS.get(booking.status, set()):
            raise IllegalTransitionError(booking.status, target)

    # ---- draft creation -------------------------------------------------

    def create_draft(
        self,
        *,
        patient_profile_id: uuid.UUID,
        doctor_id: uuid.UUID,
        clinic_location_id: uuid.UUID,
        start_time_utc: datetime,
        end_time_utc: datetime,
        fee_charged: int,
        address_snapshot: str,
        source: BookingSource = BookingSource.USER,
        ttl: timedelta = DRAFT_TTL,
    ) -> Booking:
        idempotency_key = f"{patient_profile_id}:{doctor_id}:{start_time_utc.isoformat()}"

        existing = self.session.exec(
            select(Booking).where(Booking.idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            return existing

        if source == BookingSource.USER:
            self._enforce_draft_abuse_guards(patient_profile_id, doctor_id)

        booking = Booking(
            patient_profile_id=patient_profile_id,
            doctor_id=doctor_id,
            clinic_location_id=clinic_location_id,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
            status=BookingStatus.DRAFT,
            source=source,
            fee_charged=fee_charged,
            address_snapshot=address_snapshot,
            expires_at=now_utc() + ttl,
            idempotency_key=idempotency_key,
        )
        self.session.add(booking)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise SlotUnavailableError("this slot was just taken by another booking") from exc

        self.session.refresh(booking)
        return booking

    def _enforce_draft_abuse_guards(self, patient_profile_id: uuid.UUID, doctor_id: uuid.UUID) -> None:
        active_statuses = (BookingStatus.DRAFT, BookingStatus.PENDING)

        total_active = self.session.exec(
            select(Booking).where(
                Booking.patient_profile_id == patient_profile_id,
                Booking.status.in_(active_statuses),
                Booking.source == BookingSource.USER,
            )
        ).all()
        if len(total_active) >= MAX_ACTIVE_DRAFTS_PER_PROFILE:
            raise BookingConflictError(
                f"maximum {MAX_ACTIVE_DRAFTS_PER_PROFILE} active drafts per profile reached"
            )

        with_this_doctor = [b for b in total_active if b.doctor_id == doctor_id]
        if with_this_doctor:
            raise BookingConflictError("only one active draft per doctor is allowed")

    # ---- patient confirm: draft -> pending -------------------------------

    def confirm(self, booking: Booking) -> Booking:
        self._assert_legal(booking, BookingStatus.PENDING)
        if booking.expires_at is not None and booking.expires_at < now_utc():
            raise PolicyViolationError("this draft has expired; please pick a new slot")

        booking.status = BookingStatus.PENDING
        booking.expires_at = _pending_ttl(booking.start_time_utc)
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    # ---- doctor accept: pending -> confirmed -----------------------------

    def doctor_accept(self, booking: Booking) -> Booking:
        self._assert_legal(booking, BookingStatus.CONFIRMED)
        booking.status = BookingStatus.CONFIRMED
        booking.confirmed_at = now_utc()
        booking.expires_at = None
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    # ---- doctor reject: pending -> rejected -------------------------------

    def doctor_reject(self, booking: Booking, *, reason: str) -> Booking:
        self._assert_legal(booking, BookingStatus.REJECTED)
        booking.status = BookingStatus.REJECTED
        booking.rejected_reason = reason
        booking.expires_at = None
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    # ---- cancellation ------------------------------------------------------

    def cancel(
        self,
        booking: Booking,
        *,
        cancelled_by: CancelledBy,
        reason: str,
        cancellation_policy_hours: int,
    ) -> Booking:
        self._assert_legal(booking, BookingStatus.CANCELLED)

        if cancelled_by == CancelledBy.PATIENT:
            deadline = booking.start_time_utc - timedelta(hours=cancellation_policy_hours)
            if now_utc() > deadline:
                raise PolicyViolationError(
                    f"cancellation window has passed ({cancellation_policy_hours}h before appointment)"
                )

        booking.status = BookingStatus.CANCELLED
        booking.cancelled_by = cancelled_by
        booking.cancelled_reason = reason
        booking.cancelled_at = now_utc()
        booking.expires_at = None
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    # ---- terminal-ish states used by jobs / admin (F5 dashboard, F12 jobs) --

    def expire(self, booking: Booking) -> Booking:
        self._assert_legal(booking, BookingStatus.EXPIRED)
        booking.status = BookingStatus.EXPIRED
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    def mark_completed(self, booking: Booking) -> Booking:
        self._assert_legal(booking, BookingStatus.COMPLETED)
        booking.status = BookingStatus.COMPLETED
        booking.completed_at = now_utc()
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    def mark_no_show(self, booking: Booking) -> Booking:
        self._assert_legal(booking, BookingStatus.NO_SHOW)
        if booking.status == BookingStatus.CONFIRMED and now_utc() < booking.start_time_utc:
            raise PolicyViolationError("cannot mark no_show before the appointment start time")
        booking.status = BookingStatus.NO_SHOW
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking

    def correct_completion(self, booking: Booking, *, target: BookingStatus) -> Booking:
        """Admin 7-day correction window flipping completed <-> no_show."""
        if target not in (BookingStatus.COMPLETED, BookingStatus.NO_SHOW):
            raise PolicyViolationError("correction target must be completed or no_show")
        self._assert_legal(booking, target)

        window_end = (booking.completed_at or booking.updated_at) + timedelta(days=7)
        if now_utc() > window_end:
            raise PolicyViolationError("7-day correction window has passed")

        booking.status = target
        booking.completed_at = now_utc() if target == BookingStatus.COMPLETED else booking.completed_at
        booking.updated_at = now_utc()
        self.session.add(booking)
        self.session.commit()
        self.session.refresh(booking)
        return booking


def doctor_of(session: Session, booking: Booking) -> DoctorProfile | None:
    return session.get(DoctorProfile, booking.doctor_id)
