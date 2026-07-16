"""Unit tests for agent tools (F17), calling each `@function_tool` directly
via `on_invoke_tool` (see conftest.invoke_tool) — no LLM involved. The
central invariant these tests check (F19's red-team target): every tool
that acts on a specific patient reads identity from `MedBookAgentContext`,
never from an LLM-suppliable argument.
"""

import uuid
from datetime import timedelta

from app.agents import tools as agent_tools
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import BookingSource, BookingStatus
from app.services.state_machine import MAX_ACTIVE_DRAFTS_PER_PROFILE
from tests.agents.conftest import invoke_tool
from tests.conftest import future_slot_time, make_patient


async def test_list_specializations_tool(agent_context, specialization):
    result = await invoke_tool(agent_tools.list_specializations_tool, agent_context)
    assert any(s["slug"] == specialization.slug for s in result)


async def test_search_doctors_tool_finds_verified_doctor(agent_context, verified_doctor, specialization):
    result = await invoke_tool(
        agent_tools.search_doctors_tool,
        agent_context,
        specialization_slug=specialization.slug,
        city=None,
        fee_max=None,
    )
    assert result["total"] == 1
    assert result["results"][0]["doctor_id"] == str(verified_doctor.id)


async def test_search_doctors_tool_unknown_specialization_errors(agent_context):
    result = await invoke_tool(
        agent_tools.search_doctors_tool, agent_context, specialization_slug="not-a-real-slug", city=None, fee_max=None
    )
    assert "error" in result


async def test_get_available_slots_tool(agent_context, verified_doctor, clinic_location, availability_rule):
    today = now_utc().date()
    result = await invoke_tool(
        agent_tools.get_available_slots_tool,
        agent_context,
        doctor_id=str(verified_doctor.id),
        clinic_location_id=str(clinic_location.id),
        from_date=today.isoformat(),
        to_date=(today + timedelta(days=2)).isoformat(),
    )
    assert isinstance(result, list)
    assert len(result) > 0


async def test_create_draft_booking_tool_has_no_patient_identity_param(agent_context, verified_doctor, clinic_location):
    """Structural check: the LLM-visible schema for this tool has no way to
    name a patient_profile_id at all — identity can only come from context."""
    schema_props = agent_tools.create_draft_booking_tool.params_json_schema.get("properties", {})
    assert "patient_profile_id" not in schema_props
    assert "user_id" not in schema_props


async def test_create_draft_booking_tool_creates_draft_for_context_profile(
    agent_context, session, verified_doctor, clinic_location
):
    start, end = future_slot_time(60)
    result = await invoke_tool(
        agent_tools.create_draft_booking_tool,
        agent_context,
        doctor_id=str(verified_doctor.id),
        clinic_location_id=str(clinic_location.id),
        start_time_utc=start.isoformat(),
        end_time_utc=end.isoformat(),
    )
    assert result["status"] == BookingStatus.DRAFT.value

    booking = session.get(Booking, uuid.UUID(result["draft_booking_id"]))
    assert booking is not None
    assert booking.patient_profile_id == agent_context.active_patient_profile_id
    assert booking.source == BookingSource.USER
    assert agent_context.last_draft_booking_id == booking.id


async def test_create_draft_booking_tool_no_active_profile_errors(session, patient_user, agent_session):
    from app.agents.context import MedBookAgentContext

    context = MedBookAgentContext(
        session=session, user_id=patient_user.id, agent_session_id=agent_session.id, active_patient_profile_id=None
    )
    result = await invoke_tool(
        agent_tools.create_draft_booking_tool,
        context,
        doctor_id=str(uuid.uuid4()),
        clinic_location_id=str(uuid.uuid4()),
        start_time_utc=now_utc().isoformat(),
        end_time_utc=now_utc().isoformat(),
    )
    assert "error" in result


async def test_create_draft_booking_tool_blocks_second_draft_same_doctor(
    agent_context, verified_doctor, clinic_location
):
    start, end = future_slot_time(60)
    first = await invoke_tool(
        agent_tools.create_draft_booking_tool,
        agent_context,
        doctor_id=str(verified_doctor.id),
        clinic_location_id=str(clinic_location.id),
        start_time_utc=start.isoformat(),
        end_time_utc=end.isoformat(),
    )
    assert "error" not in first, first

    start2, end2 = future_slot_time(120)
    second = await invoke_tool(
        agent_tools.create_draft_booking_tool,
        agent_context,
        doctor_id=str(verified_doctor.id),
        clinic_location_id=str(clinic_location.id),
        start_time_utc=start2.isoformat(),
        end_time_utc=end2.isoformat(),
    )
    assert "error" in second


def _make_verified_doctor(session, specialization, *, email: str):
    from app.core.security import hash_password
    from app.models.doctor import ClinicLocation, DoctorProfile
    from app.models.enums import DoctorVerificationStatus, UserRole
    from app.models.user import User

    user = User(email=email, password_hash=hash_password("password123"), role=UserRole.DOCTOR, full_name=email)
    session.add(user)
    session.flush()
    doctor = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization.id,
        pmc_number=f"PMC-{uuid.uuid4().hex[:8]}",
        consultation_fee=1500,
        verification_status=DoctorVerificationStatus.VERIFIED,
    )
    session.add(doctor)
    session.flush()
    location = ClinicLocation(doctor_id=doctor.id, name="Clinic", address="Addr", city="Lahore")
    session.add(location)
    session.commit()
    session.refresh(doctor)
    session.refresh(location)
    return doctor, location


async def test_create_draft_booking_tool_respects_total_draft_limit(agent_context, session, specialization):
    for i in range(MAX_ACTIVE_DRAFTS_PER_PROFILE):
        doctor, location = _make_verified_doctor(session, specialization, email=f"doc-{i}@example.com")
        start, end = future_slot_time(60 + i * 60)
        result = await invoke_tool(
            agent_tools.create_draft_booking_tool,
            agent_context,
            doctor_id=str(doctor.id),
            clinic_location_id=str(location.id),
            start_time_utc=start.isoformat(),
            end_time_utc=end.isoformat(),
        )
        assert "error" not in result, result

    over_limit_doctor, over_limit_location = _make_verified_doctor(session, specialization, email="doc-overlimit@example.com")
    start, end = future_slot_time(60 + MAX_ACTIVE_DRAFTS_PER_PROFILE * 60)
    over_limit = await invoke_tool(
        agent_tools.create_draft_booking_tool,
        agent_context,
        doctor_id=str(over_limit_doctor.id),
        clinic_location_id=str(over_limit_location.id),
        start_time_utc=start.isoformat(),
        end_time_utc=end.isoformat(),
    )
    assert "error" in over_limit


async def test_set_active_profile_tool_accepts_owned_profile(agent_context, session, patient_user):
    from app.models.user import PatientProfile

    dependent = PatientProfile(user_id=patient_user.id, full_name="Dependent", relationship_label="child")
    session.add(dependent)
    session.commit()
    session.refresh(dependent)

    result = await invoke_tool(agent_tools.set_active_profile_tool, agent_context, patient_profile_id=str(dependent.id))
    assert result["active_patient_profile_id"] == str(dependent.id)
    assert agent_context.active_patient_profile_id == dependent.id


async def test_set_active_profile_tool_rejects_foreign_profile(agent_context, session):
    foreign_profile = make_patient(session, "someone-else@example.com")
    original_active = agent_context.active_patient_profile_id

    result = await invoke_tool(
        agent_tools.set_active_profile_tool, agent_context, patient_profile_id=str(foreign_profile.id)
    )
    assert "error" in result
    # Context must not have been mutated by the rejected attempt.
    assert agent_context.active_patient_profile_id == original_active


async def test_reschedule_booking_tool_cancels_and_creates_linked_draft(
    agent_context, session, verified_doctor, clinic_location
):
    start, end = future_slot_time(180)
    create_result = await invoke_tool(
        agent_tools.create_draft_booking_tool,
        agent_context,
        doctor_id=str(verified_doctor.id),
        clinic_location_id=str(clinic_location.id),
        start_time_utc=start.isoformat(),
        end_time_utc=end.isoformat(),
    )
    old_booking = session.get(Booking, uuid.UUID(create_result["draft_booking_id"]))
    # Cancellation policy requires the booking to still be pending/confirmed
    # to be a meaningful "existing booking" — but patient_cancel_booking's
    # legal-transition check only allows pending/confirmed -> cancelled, so
    # move it to pending first via the state machine, matching real usage
    # (a patient reschedules a booking they already confirmed as pending).
    from app.services.state_machine import BookingStateMachine

    BookingStateMachine(session).confirm(old_booking)

    new_start = start + timedelta(days=1)
    new_end = end + timedelta(days=1)
    result = await invoke_tool(
        agent_tools.reschedule_booking_tool,
        agent_context,
        booking_id=str(old_booking.id),
        new_start_time_utc=new_start.isoformat(),
        new_end_time_utc=new_end.isoformat(),
    )
    assert "error" not in result, result

    session.refresh(old_booking)
    assert old_booking.status == BookingStatus.CANCELLED

    new_booking = session.get(Booking, uuid.UUID(result["new_draft_booking_id"]))
    assert new_booking.rescheduled_from_id == old_booking.id
    assert new_booking.status == BookingStatus.DRAFT


async def test_get_policy_doc_tool_finds_cancellation_policy(agent_context):
    result = await invoke_tool(agent_tools.get_policy_doc_tool, agent_context, query="cancellation policy window hours")
    assert result["found"] is True
    assert result["doc"] == "cancellation_policy"


async def test_get_doctor_info_tool(agent_context, verified_doctor, clinic_location):
    result = await invoke_tool(agent_tools.get_doctor_info_tool, agent_context, doctor_id=str(verified_doctor.id))
    assert result["fee"] == verified_doctor.consultation_fee
    assert len(result["locations"]) == 1
