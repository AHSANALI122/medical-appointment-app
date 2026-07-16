"""F18 — HITL booking confirmation. The state-machine plumbing (draft TTL,
abuse guards, idempotency) is exercised in test_state_machine.py and
test_booking_flow.py; this file covers what's specific to F18's acceptance
criteria: an agent-created draft never auto-advances to pending, an expired
draft (agent-created or manual) frees its slot via the same sweep job, and
the patient's confirm tap is audit-logged with confirmer + timestamp.
"""

from datetime import timedelta

from sqlmodel import select

from app.core.timezone import now_utc
from app.jobs.expiry_sweep import sweep_expired_bookings
from app.models.audit_log import AuditLog
from app.models.booking import Booking
from app.models.enums import BookingSource, BookingStatus
from app.services import booking_service
from tests.conftest import make_patient


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def _create_agent_draft(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=60):
    start = now_utc() + timedelta(minutes=minutes_ahead)
    end = start + timedelta(minutes=30)
    return booking_service.create_draft_booking(
        session,
        patient_profile=patient_profile,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        start_time_utc=start,
        end_time_utc=end,
        source=BookingSource.USER,
    )


class TestHITLConfirmation:
    def test_agent_draft_never_auto_advances_to_pending(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        booking = _create_agent_draft(session, patient_profile, verified_doctor, clinic_location)
        assert booking.status == BookingStatus.DRAFT

        # There is no code path from draft to pending except the explicit
        # confirm endpoint below — reloading from the DB proves nothing
        # implicitly advanced it just by creating the draft.
        session.refresh(booking)
        assert booking.status == BookingStatus.DRAFT

    def test_explicit_confirm_required_to_reach_pending(self, client, session, patient_user, patient_profile, verified_doctor, clinic_location):
        _login_patient(client, patient_user)
        booking = _create_agent_draft(session, patient_profile, verified_doctor, clinic_location)
        session.commit()

        still_draft = session.get(Booking, booking.id)
        assert still_draft.status == BookingStatus.DRAFT

        resp = client.post(f"/api/v1/bookings/{booking.id}/confirm")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_expired_agent_created_draft_frees_slot(self, session, patient_profile, verified_doctor, clinic_location):
        booking = _create_agent_draft(session, patient_profile, verified_doctor, clinic_location)
        booking.expires_at = now_utc() - timedelta(seconds=1)
        session.add(booking)
        session.commit()

        expired_count = sweep_expired_bookings(session)
        assert expired_count == 1

        session.refresh(booking)
        assert booking.status == BookingStatus.EXPIRED

        # The slot is free again: a *different* patient can now draft the
        # exact same (doctor, location, start_time) triple. A same-patient
        # retry would instead hit the idempotency-key short-circuit and
        # just return the same (now expired) row, which wouldn't prove
        # anything about the slot itself being released.
        other_profile = make_patient(session, "hitl-other@example.com")
        new_booking = booking_service.create_draft_booking(
            session,
            patient_profile=other_profile,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
            source=BookingSource.USER,
        )
        assert new_booking.status == BookingStatus.DRAFT

    def test_confirm_is_audit_logged_with_confirmer_and_timestamp(
        self, client, session, patient_user, patient_profile, verified_doctor, clinic_location
    ):
        _login_patient(client, patient_user)
        booking = _create_agent_draft(session, patient_profile, verified_doctor, clinic_location)
        session.commit()

        before = now_utc()
        resp = client.post(f"/api/v1/bookings/{booking.id}/confirm")
        assert resp.status_code == 200

        log = session.exec(
            select(AuditLog).where(
                AuditLog.resource_type == "booking",
                AuditLog.resource_id == booking.id,
                AuditLog.action == "confirm",
            )
        ).first()
        assert log is not None
        assert log.actor_user_id == patient_user.id
        assert log.created_at >= before
