"""F27 — patient data export ("download my data").

Scope is *the patient's own* data, resolved from the JWT-owned user_id and
the profiles hanging off it — never from a client-supplied id (CLAUDE.md
rule 8). The two judgement calls worth stating:

  - **Clinical notes are included only where `is_shared_with_patient`**,
    matching what F6 already lets them read in the UI. An export is a
    convenience view over data the patient can already see; it is not a
    backdoor around the doctor's private-by-default notes.
  - **Medical history includes every version**, not just the current one.
    The table is append-only by design (F24), the older versions are the
    patient's own words about their own body, and "export my data" that
    silently drops history isn't complete.

Every export is written to the audit log before the payload is built: this
reads medical history, and CLAUDE.md rule 7 requires all such reads to be
audited.
"""

from typing import Any

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.audit_log import AuditLog
from app.models.booking import Booking
from app.models.medical_history import MedicalHistory
from app.models.note import ClinicalNote, PatientNote
from app.models.review import Review
from app.models.user import PatientProfile, User

logger = get_logger(__name__)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def build_export(session: Session, *, user: User) -> dict:
    profiles = list(
        session.exec(select(PatientProfile).where(PatientProfile.user_id == user.id)).all()
    )
    profile_ids = [p.id for p in profiles]

    _audit_export(session, user=user, profile_ids=profile_ids)

    return {
        "exported_at": now_utc().isoformat(),
        "account": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role.value,
            "notification_preference": user.notification_preference.value,
            "created_at": _iso(user.created_at),
        },
        "patient_profiles": [
            {
                "id": str(p.id),
                "relationship_label": p.relationship_label,
                "full_name": p.full_name,
                "date_of_birth": _iso(p.date_of_birth),
                "created_at": _iso(p.created_at),
            }
            for p in profiles
        ],
        "bookings": _export_bookings(session, profile_ids=profile_ids),
        "medical_history": _export_medical_history(session, profile_ids=profile_ids),
        "reviews": _export_reviews(session, profile_ids=profile_ids),
    }


def _export_bookings(session: Session, *, profile_ids: list) -> list[dict]:
    if not profile_ids:
        return []

    bookings = list(
        session.exec(
            select(Booking)
            .where(Booking.patient_profile_id.in_(profile_ids))
            .order_by(Booking.start_time_utc)
        ).all()
    )
    if not bookings:
        return []

    booking_ids = [b.id for b in bookings]

    # Fetched in two bulk queries rather than per-booking lookups inside the
    # loop — an export is the one endpoint guaranteed to touch every booking
    # a patient ever made, so an N+1 here scales with the most active users.
    patient_notes = {
        n.booking_id: n
        for n in session.exec(select(PatientNote).where(PatientNote.booking_id.in_(booking_ids))).all()
    }
    shared_clinical_notes = {
        n.booking_id: n
        for n in session.exec(
            select(ClinicalNote).where(
                ClinicalNote.booking_id.in_(booking_ids),
                ClinicalNote.is_shared_with_patient.is_(True),
            )
        ).all()
    }

    exported = []
    for booking in bookings:
        patient_note = patient_notes.get(booking.id)
        clinical_note = shared_clinical_notes.get(booking.id)
        exported.append(
            {
                "id": str(booking.id),
                "patient_profile_id": str(booking.patient_profile_id),
                "doctor_id": str(booking.doctor_id),
                "status": booking.status.value,
                "start_time_utc": _iso(booking.start_time_utc),
                "end_time_utc": _iso(booking.end_time_utc),
                "fee_charged": booking.fee_charged,
                "address_snapshot": booking.address_snapshot,
                "cancelled_by": booking.cancelled_by.value if booking.cancelled_by else None,
                "cancelled_reason": booking.cancelled_reason,
                "rejected_reason": booking.rejected_reason,
                "created_at": _iso(booking.created_at),
                "confirmed_at": _iso(booking.confirmed_at),
                "completed_at": _iso(booking.completed_at),
                "my_note": patient_note.content if patient_note else None,
                "doctor_note_shared_with_me": clinical_note.content if clinical_note else None,
            }
        )
    return exported


def _export_medical_history(session: Session, *, profile_ids: list) -> list[dict]:
    if not profile_ids:
        return []
    rows = session.exec(
        select(MedicalHistory)
        .where(MedicalHistory.patient_profile_id.in_(profile_ids))
        .order_by(MedicalHistory.patient_profile_id, MedicalHistory.version)
    ).all()
    return [
        {
            "patient_profile_id": str(r.patient_profile_id),
            "version": r.version,
            "blood_group": r.blood_group,
            "allergies": r.allergies,
            "medications": r.medications,
            "chronic_conditions": r.chronic_conditions,
            "surgeries": r.surgeries,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


def _export_reviews(session: Session, *, profile_ids: list) -> list[dict]:
    if not profile_ids:
        return []
    rows = session.exec(select(Review).where(Review.patient_profile_id.in_(profile_ids))).all()
    return [
        {
            "id": str(r.id),
            "booking_id": str(r.booking_id),
            "doctor_id": str(r.doctor_id),
            "rating": r.rating,
            "comment": r.comment,
            "moderation_status": r.moderation_status.value,
            "doctor_reply": r.doctor_reply,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


def _audit_export(session: Session, *, user: User, profile_ids: list) -> None:
    """An export reads medical history, so it is an audited read (CLAUDE.md
    rule 7) — one row per profile whose history is leaving the system."""
    for profile_id in profile_ids:
        session.add(
            AuditLog(
                actor_user_id=user.id,
                action="data_export",
                resource_type="patient_profile",
                resource_id=profile_id,
            )
        )
    session.commit()
    logger.info("account.data_exported", user_id=str(user.id), profile_count=len(profile_ids))
