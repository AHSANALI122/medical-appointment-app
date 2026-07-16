"""F6 — Appointment Notes.

Patient notes (reason/symptoms) and doctor clinical notes are both scoped
1:1 to a booking and encrypted at rest (EncryptedString). Access rules:

- Patient note: owning patient may read/write; the booking's doctor may
  read (the reason a patient booked is naturally visible to who they're
  seeing) but never write it.
- Clinical note: owning doctor may read/write; the patient may read it
  only when `is_shared_with_patient` is set — this is the access-control
  boundary the acceptance test exercises.
"""

import uuid
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.booking import Booking
from app.models.doctor import DoctorProfile
from app.models.note import ClinicalNote, PatientNote
from app.models.user import PatientProfile


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_booking_or_404(session: Session, booking_id: uuid.UUID) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFoundError("booking not found")
    return booking


def _assert_patient_owns_booking(booking: Booking, patient_profile: PatientProfile) -> None:
    if booking.patient_profile_id != patient_profile.id:
        raise NotFoundError("booking not found")


def _assert_doctor_owns_booking(booking: Booking, doctor: DoctorProfile) -> None:
    if booking.doctor_id != doctor.id:
        raise NotFoundError("booking not found")


# ---- patient note ------------------------------------------------------


def upsert_patient_note(
    session: Session, *, booking_id: uuid.UUID, patient_profile: PatientProfile, content: str
) -> PatientNote:
    booking = _get_booking_or_404(session, booking_id)
    _assert_patient_owns_booking(booking, patient_profile)

    note = session.exec(select(PatientNote).where(PatientNote.booking_id == booking_id)).first()
    if note is None:
        note = PatientNote(
            booking_id=booking_id, patient_profile_id=patient_profile.id, content=content
        )
    else:
        note.content = content
        note.updated_at = _utcnow()
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def get_patient_note_for_patient(
    session: Session, *, booking_id: uuid.UUID, patient_profile: PatientProfile
) -> PatientNote:
    booking = _get_booking_or_404(session, booking_id)
    _assert_patient_owns_booking(booking, patient_profile)
    return _get_patient_note_or_404(session, booking_id)


def get_patient_note_for_doctor(
    session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile
) -> PatientNote:
    booking = _get_booking_or_404(session, booking_id)
    _assert_doctor_owns_booking(booking, doctor)
    return _get_patient_note_or_404(session, booking_id)


def _get_patient_note_or_404(session: Session, booking_id: uuid.UUID) -> PatientNote:
    note = session.exec(select(PatientNote).where(PatientNote.booking_id == booking_id)).first()
    if note is None:
        raise NotFoundError("patient note not found")
    return note


# ---- clinical note -------------------------------------------------------


def upsert_clinical_note(
    session: Session,
    *,
    booking_id: uuid.UUID,
    doctor: DoctorProfile,
    content: str,
    is_shared_with_patient: bool,
) -> ClinicalNote:
    booking = _get_booking_or_404(session, booking_id)
    _assert_doctor_owns_booking(booking, doctor)

    note = session.exec(select(ClinicalNote).where(ClinicalNote.booking_id == booking_id)).first()
    if note is None:
        note = ClinicalNote(
            booking_id=booking_id,
            doctor_id=doctor.id,
            content=content,
            is_shared_with_patient=is_shared_with_patient,
        )
    else:
        note.content = content
        note.is_shared_with_patient = is_shared_with_patient
        note.updated_at = _utcnow()
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


def get_clinical_note_for_doctor(
    session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile
) -> ClinicalNote:
    booking = _get_booking_or_404(session, booking_id)
    _assert_doctor_owns_booking(booking, doctor)
    return _get_clinical_note_or_404(session, booking_id)


def get_clinical_note_for_patient(
    session: Session, *, booking_id: uuid.UUID, patient_profile: PatientProfile
) -> ClinicalNote:
    booking = _get_booking_or_404(session, booking_id)
    _assert_patient_owns_booking(booking, patient_profile)
    note = _get_clinical_note_or_404(session, booking_id)
    if not note.is_shared_with_patient:
        raise ForbiddenError("this clinical note has not been shared with you")
    return note


def _get_clinical_note_or_404(session: Session, booking_id: uuid.UUID) -> ClinicalNote:
    note = session.exec(select(ClinicalNote).where(ClinicalNote.booking_id == booking_id)).first()
    if note is None:
        raise NotFoundError("clinical note not found")
    return note
