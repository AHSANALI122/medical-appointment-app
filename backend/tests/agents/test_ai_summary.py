"""F20 — AI visit summary: doctor-only, draft-only (HITL), never
patient-facing, and never persisted until the doctor saves it themselves
through the existing clinical-note endpoint.
"""

from sqlmodel import select

from app.models.note import ClinicalNote
from app.services import feature_flag_service
from tests.agents.fake_model import json_response

_DRAFT_PAYLOAD = {
    "chief_complaint": "Fever and sore throat for 3 days",
    "assessment": "Likely viral pharyngitis",
    "plan": "Rest, fluids, follow up in a week if not improving",
}


def _login_doctor(client):
    resp = client.post("/api/v1/auth/login", json={"email": "doctor@example.com", "password": "password123"})
    assert resp.status_code == 200


def _confirmed_booking(session, patient_profile, verified_doctor, clinic_location):
    from app.services import booking_service
    from app.services.state_machine import BookingStateMachine
    from tests.conftest import future_slot_time

    start, end = future_slot_time(180)
    booking = booking_service.create_draft_booking(
        session, patient_profile=patient_profile, doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id, start_time_utc=start, end_time_utc=end,
    )
    machine = BookingStateMachine(session)
    booking = machine.confirm(booking)
    return machine.doctor_accept(booking)


def test_doctor_can_generate_draft(client, session, patient_profile, verified_doctor, clinic_location, fake_llm):
    booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
    fake_llm([json_response(_DRAFT_PAYLOAD)])
    _login_doctor(client)

    resp = client.post(
        f"/api/v1/bookings/{booking.id}/clinical-note/ai-draft", json={"rough_notes": "fever sore throat 3d"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chief_complaint"] == _DRAFT_PAYLOAD["chief_complaint"]
    assert body["plan"] == _DRAFT_PAYLOAD["plan"]


def test_draft_is_never_persisted(client, session, patient_profile, verified_doctor, clinic_location, fake_llm):
    booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
    fake_llm([json_response(_DRAFT_PAYLOAD)])
    _login_doctor(client)

    client.post(f"/api/v1/bookings/{booking.id}/clinical-note/ai-draft", json={"rough_notes": "fever sore throat"})

    saved = session.exec(select(ClinicalNote).where(ClinicalNote.booking_id == booking.id)).first()
    assert saved is None


def test_patient_cannot_generate_draft(client, session, patient_user, patient_profile, verified_doctor, clinic_location):
    booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200

    resp = client.post(f"/api/v1/bookings/{booking.id}/clinical-note/ai-draft", json={"rough_notes": "test"})
    assert resp.status_code == 403


def test_other_doctor_cannot_generate_draft_for_foreign_booking(
    client_factory, session, patient_profile, verified_doctor, clinic_location, specialization
):
    from tests.agents.test_agent_tools import _make_verified_doctor

    booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
    _make_verified_doctor(session, specialization, email="other-doc@example.com")

    other_client = client_factory()
    resp = other_client.post("/api/v1/auth/login", json={"email": "other-doc@example.com", "password": "password123"})
    assert resp.status_code == 200

    resp = other_client.post(f"/api/v1/bookings/{booking.id}/clinical-note/ai-draft", json={"rough_notes": "test"})
    assert resp.status_code == 403


def test_disabled_feature_flag_blocks_route(client, session, patient_profile, verified_doctor, clinic_location):
    feature_flag_service.set_enabled(session, key=feature_flag_service.AI_SUMMARY, enabled=False)
    booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
    _login_doctor(client)

    resp = client.post(f"/api/v1/bookings/{booking.id}/clinical-note/ai-draft", json={"rough_notes": "test"})
    assert resp.status_code == 403


def test_empty_rough_notes_rejected(client, session, patient_profile, verified_doctor, clinic_location):
    booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
    _login_doctor(client)

    resp = client.post(f"/api/v1/bookings/{booking.id}/clinical-note/ai-draft", json={"rough_notes": ""})
    assert resp.status_code == 422
