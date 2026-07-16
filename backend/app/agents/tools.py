"""Agent tools — thin, Pydantic-validated wrappers around the existing
service layer (CLAUDE.md rule 9). Every tool that touches a specific
patient's data reads `patient_profile_id` from `ctx.context`, never from an
LLM-supplied argument (CLAUDE.md rule 8) — this is the invariant the F19
red-team suite checks directly. `create_draft_booking_tool` and
`reschedule_booking_tool` only ever reach `draft` status (F18) — there is no
tool that advances a booking to `pending`.
"""

import json
import uuid
from datetime import date, datetime, timedelta

from agents import RunContextWrapper, function_tool
from sqlmodel import select

from app.agents.context import MedBookAgentContext
from app.agents.policy_docs import search_policy_docs
from app.core.exceptions import MedBookError
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.doctor import DoctorProfile
from app.models.enums import BookingSource, BookingStatus
from app.models.taxonomy import SpecializationTaxonomy
from app.models.user import PatientProfile, User
from app.services import agent_session_service, booking_service, doctor_service, slot_service


def _active_patient_profile(ctx: RunContextWrapper[MedBookAgentContext]) -> PatientProfile | None:
    context = ctx.context
    if context.active_patient_profile_id is None:
        return None
    return context.session.get(PatientProfile, context.active_patient_profile_id)


@function_tool
def list_specializations_tool(ctx: RunContextWrapper[MedBookAgentContext]) -> str:
    """List the fixed specialization taxonomy the triage agent must route
    into — never invent a specialization outside this closed set."""
    rows = ctx.context.session.exec(
        select(SpecializationTaxonomy).where(SpecializationTaxonomy.is_active == True)  # noqa: E712
    ).all()
    return json.dumps(
        [{"slug": r.slug, "name_en": r.name_en, "name_ur": r.name_ur} for r in rows]
    )


@function_tool
def search_doctors_tool(
    ctx: RunContextWrapper[MedBookAgentContext],
    specialization_slug: str | None,
    city: str | None,
    fee_max: int | None,
) -> str:
    """Search verified doctors by specialization slug (from
    list_specializations_tool), city, and maximum fee in PKR."""
    session = ctx.context.session
    specialization_id = None
    if specialization_slug:
        spec = session.exec(
            select(SpecializationTaxonomy).where(SpecializationTaxonomy.slug == specialization_slug)
        ).first()
        if spec is None:
            return json.dumps({"error": f"unknown specialization slug {specialization_slug!r}"})
        specialization_id = spec.id

    doctors, total = doctor_service.search_doctors(
        session,
        specialization_id=specialization_id,
        city=city,
        fee_min=None,
        fee_max=fee_max,
        offset=0,
        limit=10,
    )
    results = []
    for doctor in doctors:
        user = session.get(User, doctor.user_id)
        results.append(
            {
                "doctor_id": str(doctor.id),
                "name": user.full_name if user else None,
                "fee": doctor.consultation_fee,
            }
        )
    return json.dumps({"total": total, "results": results})


@function_tool
def get_available_slots_tool(
    ctx: RunContextWrapper[MedBookAgentContext],
    doctor_id: str,
    clinic_location_id: str,
    from_date: str,
    to_date: str,
) -> str:
    """List open slots for a doctor at a clinic between two dates
    (YYYY-MM-DD, Asia/Karachi local dates)."""
    try:
        slots = slot_service.generate_available_slots(
            ctx.context.session,
            doctor_id=uuid.UUID(doctor_id),
            clinic_location_id=uuid.UUID(clinic_location_id),
            from_date=date.fromisoformat(from_date),
            to_date=date.fromisoformat(to_date),
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps(
        [{"start_time_utc": s.start_time_utc.isoformat(), "end_time_utc": s.end_time_utc.isoformat()} for s in slots]
    )


@function_tool
def create_draft_booking_tool(
    ctx: RunContextWrapper[MedBookAgentContext],
    doctor_id: str,
    clinic_location_id: str,
    start_time_utc: str,
    end_time_utc: str,
) -> str:
    """Create a `draft` booking hold for the currently active patient
    profile. This NEVER confirms a booking — the patient must still tap
    Confirm in the app within 10 minutes, or the hold expires."""
    patient_profile = _active_patient_profile(ctx)
    if patient_profile is None:
        return json.dumps({"error": "no active patient profile — call set_active_profile first"})

    try:
        booking = booking_service.create_draft_booking(
            ctx.context.session,
            patient_profile=patient_profile,
            doctor_id=uuid.UUID(doctor_id),
            clinic_location_id=uuid.UUID(clinic_location_id),
            start_time_utc=datetime.fromisoformat(start_time_utc),
            end_time_utc=datetime.fromisoformat(end_time_utc),
            source=BookingSource.USER,
        )
    except (MedBookError, ValueError) as exc:
        return json.dumps({"error": getattr(exc, "message", str(exc))})

    ctx.context.last_draft_booking_id = booking.id
    return json.dumps(
        {
            "draft_booking_id": str(booking.id),
            "status": booking.status.value,
            "fee_charged": booking.fee_charged,
            "address_snapshot": booking.address_snapshot,
            "expires_at": booking.expires_at.isoformat() if booking.expires_at else None,
            "note": "The patient must confirm this in the app before it becomes a real request.",
        }
    )


@function_tool
def get_patient_bookings_tool(
    ctx: RunContextWrapper[MedBookAgentContext], status: str | None
) -> str:
    """List the active patient profile's bookings, optionally filtered by
    status (draft/pending/confirmed/completed/cancelled/rejected/expired/no_show)."""
    patient_profile = _active_patient_profile(ctx)
    if patient_profile is None:
        return json.dumps({"error": "no active patient profile — call set_active_profile first"})

    try:
        status_enum = BookingStatus(status) if status else None
    except ValueError:
        return json.dumps({"error": f"unknown status {status!r}"})

    bookings = booking_service.list_patient_bookings(
        ctx.context.session, patient_profile=patient_profile, status=status_enum
    )
    return json.dumps(
        [
            {
                "booking_id": str(b.id),
                "doctor_id": str(b.doctor_id),
                "start_time_utc": b.start_time_utc.isoformat(),
                "status": b.status.value,
                "fee_charged": b.fee_charged,
            }
            for b in bookings
        ]
    )


@function_tool
def check_cancellation_policy_tool(ctx: RunContextWrapper[MedBookAgentContext], booking_id: str) -> str:
    """Check whether a booking can still be cancelled/rescheduled under its
    doctor's cancellation policy window."""
    patient_profile = _active_patient_profile(ctx)
    if patient_profile is None:
        return json.dumps({"error": "no active patient profile — call set_active_profile first"})

    session = ctx.context.session
    booking = session.get(Booking, uuid.UUID(booking_id))
    if booking is None or booking.patient_profile_id != patient_profile.id:
        return json.dumps({"error": "booking not found"})

    doctor = session.get(DoctorProfile, booking.doctor_id)
    if doctor is None:
        return json.dumps({"error": "doctor not found"})

    deadline = booking.start_time_utc - timedelta(hours=doctor.cancellation_policy_hours)
    return json.dumps(
        {
            "allowed": now_utc() <= deadline,
            "deadline_utc": deadline.isoformat(),
            "policy_hours": doctor.cancellation_policy_hours,
        }
    )


@function_tool
def reschedule_booking_tool(
    ctx: RunContextWrapper[MedBookAgentContext],
    booking_id: str,
    new_start_time_utc: str,
    new_end_time_utc: str,
) -> str:
    """Reschedule a booking: cancels the existing one (subject to the same
    cancellation-policy window) and creates a new `draft` at the new time,
    linked via rescheduled_from_id. The new draft still requires an explicit
    patient Confirm tap — rescheduling is not auto-confirmed."""
    patient_profile = _active_patient_profile(ctx)
    if patient_profile is None:
        return json.dumps({"error": "no active patient profile — call set_active_profile first"})

    session = ctx.context.session
    old_booking = session.get(Booking, uuid.UUID(booking_id))
    if old_booking is None or old_booking.patient_profile_id != patient_profile.id:
        return json.dumps({"error": "booking not found"})

    try:
        cancelled = booking_service.patient_cancel_booking(
            session,
            booking_id=old_booking.id,
            patient_profile=patient_profile,
            reason="rescheduled by patient via chat assistant",
        )
        new_booking = booking_service.create_draft_booking(
            session,
            patient_profile=patient_profile,
            doctor_id=old_booking.doctor_id,
            clinic_location_id=old_booking.clinic_location_id,
            start_time_utc=datetime.fromisoformat(new_start_time_utc),
            end_time_utc=datetime.fromisoformat(new_end_time_utc),
            source=BookingSource.USER,
        )
    except (MedBookError, ValueError) as exc:
        return json.dumps({"error": getattr(exc, "message", str(exc))})

    new_booking.rescheduled_from_id = cancelled.id
    session.add(new_booking)
    session.commit()
    session.refresh(new_booking)

    ctx.context.last_draft_booking_id = new_booking.id
    return json.dumps(
        {
            "cancelled_booking_id": str(cancelled.id),
            "new_draft_booking_id": str(new_booking.id),
            "expires_at": new_booking.expires_at.isoformat() if new_booking.expires_at else None,
            "note": "The patient must confirm the new draft in the app.",
        }
    )


@function_tool
def get_doctor_info_tool(ctx: RunContextWrapper[MedBookAgentContext], doctor_id: str) -> str:
    """Exact doctor/fee/location lookup — structured DB data, never RAG, so
    fees can never be hallucinated."""
    session = ctx.context.session
    doctor = session.get(DoctorProfile, uuid.UUID(doctor_id))
    if doctor is None:
        return json.dumps({"error": "doctor not found"})

    user = session.get(User, doctor.user_id)
    locations = doctor_service.list_clinic_locations(session, doctor.id)
    return json.dumps(
        {
            "name": user.full_name if user else None,
            "fee": doctor.consultation_fee,
            "verified": doctor.verification_status.value,
            "cancellation_policy_hours": doctor.cancellation_policy_hours,
            "locations": [
                {"id": str(loc.id), "name": loc.name, "address": loc.address, "city": loc.city}
                for loc in locations
            ],
        }
    )


@function_tool
def get_policy_doc_tool(ctx: RunContextWrapper[MedBookAgentContext], query: str) -> str:
    """Look up an answer from MedBook's static policy/help docs (cancellation
    policy, how booking works, emergencies) — not doctor or fee data, use
    get_doctor_info_tool for that."""
    return search_policy_docs(query)


@function_tool
def set_active_profile_tool(ctx: RunContextWrapper[MedBookAgentContext], patient_profile_id: str) -> str:
    """Switch which family member ('Ammi', 'self', etc.) subsequent tool
    calls act on for this session. Only profiles owned by the signed-in
    user can be selected — enforced server-side, not by what the model says."""
    context = ctx.context
    try:
        agent_session = agent_session_service.get_owned_session(
            context.session, session_id=context.agent_session_id, user_id=context.user_id
        )
        agent_session_service.set_active_profile(
            context.session,
            agent_session=agent_session,
            user_id=context.user_id,
            patient_profile_id=uuid.UUID(patient_profile_id),
        )
    except (MedBookError, ValueError) as exc:
        return json.dumps({"error": getattr(exc, "message", str(exc))})

    context.active_patient_profile_id = uuid.UUID(patient_profile_id)
    return json.dumps({"active_patient_profile_id": patient_profile_id})


PROFILE_TOOLS = [set_active_profile_tool]
BOOKING_TOOLS = [
    list_specializations_tool,
    search_doctors_tool,
    get_available_slots_tool,
    create_draft_booking_tool,
    *PROFILE_TOOLS,
]
RESCHEDULE_TOOLS = [get_patient_bookings_tool, check_cancellation_policy_tool, reschedule_booking_tool, *PROFILE_TOOLS]
FAQ_TOOLS = [get_doctor_info_tool, get_policy_doc_tool]
