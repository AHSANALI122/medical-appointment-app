"""F24 — Patient Medical History Profile.

Per-PatientProfile (family-account aware): allergies, medications, chronic
conditions, blood group, surgeries. Patient edits anytime; every edit inserts
a new `MedicalHistory` row with `version` bumped — the table itself is the
append-only version history, so there's nothing extra to keep in sync.

Doctor access window (v1 fix from spec.md F24): a doctor may read a
profile's history only while they hold a booking with that profile in
`pending` / `confirmed` / `completed` state whose appointment start time
falls within the last 12 months. A doctor with only `cancelled` / `rejected`
bookings, or bookings older than 12 months, gets a 403 — not a 404, since
the booking existing-but-stale is a meaningfully different case from no
relationship ever having existed, same distinction note_service draws
between ForbiddenError and NotFoundError.
"""

import uuid
from datetime import timedelta

from sqlmodel import Session, func, select

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.doctor import DoctorProfile
from app.models.enums import BookingStatus
from app.models.medical_history import MedicalHistory
from app.models.user import PatientProfile

DOCTOR_ACCESS_WINDOW = timedelta(days=365)
_DOCTOR_ACCESS_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)


def get_current(session: Session, *, patient_profile_id: uuid.UUID) -> MedicalHistory | None:
    return session.exec(
        select(MedicalHistory)
        .where(MedicalHistory.patient_profile_id == patient_profile_id)
        .order_by(MedicalHistory.version.desc())
        .limit(1)
    ).first()


def get_current_for_patient(session: Session, *, patient_profile: PatientProfile) -> MedicalHistory:
    history = get_current(session, patient_profile_id=patient_profile.id)
    if history is None:
        raise NotFoundError("medical history not found")
    return history


def list_versions(session: Session, *, patient_profile: PatientProfile) -> list[MedicalHistory]:
    return list(
        session.exec(
            select(MedicalHistory)
            .where(MedicalHistory.patient_profile_id == patient_profile.id)
            .order_by(MedicalHistory.version.desc())
        ).all()
    )


def upsert(
    session: Session,
    *,
    patient_profile: PatientProfile,
    editor_user_id: uuid.UUID,
    blood_group: str | None,
    allergies: str | None,
    medications: str | None,
    chronic_conditions: str | None,
    surgeries: str | None,
) -> MedicalHistory:
    current = get_current(session, patient_profile_id=patient_profile.id)
    next_version = (current.version + 1) if current else 1

    history = MedicalHistory(
        patient_profile_id=patient_profile.id,
        version=next_version,
        blood_group=blood_group,
        allergies=allergies,
        medications=medications,
        chronic_conditions=chronic_conditions,
        surgeries=surgeries,
        edited_by_user_id=editor_user_id,
    )
    session.add(history)
    session.commit()
    session.refresh(history)
    return history


def _doctor_has_qualifying_booking(session: Session, *, doctor: DoctorProfile, patient_profile_id: uuid.UUID) -> bool:
    cutoff = now_utc() - DOCTOR_ACCESS_WINDOW
    count = session.exec(
        select(func.count()).where(
            Booking.doctor_id == doctor.id,
            Booking.patient_profile_id == patient_profile_id,
            Booking.status.in_(_DOCTOR_ACCESS_STATUSES),
            Booking.start_time_utc >= cutoff,
        )
    ).one()
    return count > 0


def get_for_doctor(
    session: Session, *, doctor: DoctorProfile, patient_profile_id: uuid.UUID
) -> MedicalHistory:
    if not _doctor_has_qualifying_booking(session, doctor=doctor, patient_profile_id=patient_profile_id):
        raise ForbiddenError(
            "you may only view this patient's medical history while you hold an active "
            "(pending/confirmed/completed) booking with them from the last 12 months"
        )
    history = get_current(session, patient_profile_id=patient_profile_id)
    if history is None:
        raise NotFoundError("medical history not found")
    return history


def get_for_doctor_via_booking(
    session: Session, *, doctor: DoctorProfile, booking_id: uuid.UUID
) -> MedicalHistory:
    """Entry point used by the doctor-facing endpoint: history is 'auto-
    attached read-only to bookings' per spec.md, so a doctor reaches it
    through a specific booking. Row-level auth first (doctor A requesting a
    booking that isn't theirs gets 404, mirroring get_doctor_booking_or_403),
    then the 12-month access-window check runs against that booking's
    patient profile."""
    booking = session.get(Booking, booking_id)
    if booking is None or booking.doctor_id != doctor.id:
        raise NotFoundError("booking not found")
    return get_for_doctor(session, doctor=doctor, patient_profile_id=booking.patient_profile_id)
