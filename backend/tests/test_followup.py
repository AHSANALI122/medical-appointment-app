"""F20 — follow-up scheduling: immediate notify when the target date is
within the 60-day booking horizon, deferred + sweep-job pickup otherwise.
"""

from datetime import timedelta

from sqlmodel import select

from app.core.exceptions import PolicyViolationError
from app.core.timezone import now_local
from app.jobs.followup_sweep import run_followup_sweep
from app.models.enums import FollowUpStatus
from app.models.notification import Notification
from app.services import booking_service, feature_flag_service, followup_service
from app.services.state_machine import BookingStateMachine
from tests.conftest import future_slot_time


def _login_doctor(client):
    resp = client.post("/api/v1/auth/login", json={"email": "doctor@example.com", "password": "password123"})
    assert resp.status_code == 200


def _confirmed_booking(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=180):
    start, end = future_slot_time(minutes_ahead)
    booking = booking_service.create_draft_booking(
        session, patient_profile=patient_profile, doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id, start_time_utc=start, end_time_utc=end,
    )
    machine = BookingStateMachine(session)
    booking = machine.confirm(booking)
    return machine.doctor_accept(booking)


class TestScheduleFollowUp:
    def test_within_horizon_notifies_immediately(self, session, patient_profile, verified_doctor, clinic_location):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        follow_up = followup_service.schedule_follow_up(
            session, booking_id=booking.id, doctor=verified_doctor, weeks=1
        )
        assert follow_up.status == FollowUpStatus.NOTIFIED
        assert follow_up.target_date == now_local().date() + timedelta(weeks=1)

        notif = session.exec(select(Notification).where(Notification.user_id == patient_profile.user_id)).first()
        assert notif is not None

    def test_beyond_horizon_is_deferred(self, session, patient_profile, verified_doctor, clinic_location):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        follow_up = followup_service.schedule_follow_up(
            session, booking_id=booking.id, doctor=verified_doctor, weeks=52
        )
        assert follow_up.status == FollowUpStatus.DEFERRED

    def test_rejects_out_of_range_weeks(self, session, patient_profile, verified_doctor, clinic_location):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        try:
            followup_service.schedule_follow_up(session, booking_id=booking.id, doctor=verified_doctor, weeks=0)
            raise AssertionError("expected PolicyViolationError")
        except PolicyViolationError:
            pass

    def test_rejects_non_confirmed_booking(self, session, patient_profile, verified_doctor, clinic_location):
        start, end = future_slot_time(60)
        draft = booking_service.create_draft_booking(
            session, patient_profile=patient_profile, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=start, end_time_utc=end,
        )
        try:
            followup_service.schedule_follow_up(session, booking_id=draft.id, doctor=verified_doctor, weeks=2)
            raise AssertionError("expected PolicyViolationError")
        except PolicyViolationError:
            pass


class TestFollowUpSweep:
    def test_sweep_notifies_once_target_date_enters_horizon(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        follow_up = followup_service.schedule_follow_up(
            session, booking_id=booking.id, doctor=verified_doctor, weeks=52
        )
        assert follow_up.status == FollowUpStatus.DEFERRED

        # Simulate time passing until the target date is inside the horizon.
        follow_up.target_date = now_local().date() + timedelta(days=10)
        session.add(follow_up)
        session.commit()

        notified_count = run_followup_sweep(session)
        assert notified_count == 1

        session.refresh(follow_up)
        assert follow_up.status == FollowUpStatus.NOTIFIED

    def test_sweep_leaves_still_deferred_entries_alone(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        follow_up = followup_service.schedule_follow_up(
            session, booking_id=booking.id, doctor=verified_doctor, weeks=52
        )
        notified_count = run_followup_sweep(session)
        assert notified_count == 0
        session.refresh(follow_up)
        assert follow_up.status == FollowUpStatus.DEFERRED


class TestFollowUpRouter:
    def test_doctor_can_schedule_follow_up_via_api(self, client, session, patient_profile, verified_doctor, clinic_location):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        _login_doctor(client)
        resp = client.post(f"/api/v1/bookings/{booking.id}/follow-up", json={"weeks": 2})
        assert resp.status_code == 201
        assert resp.json()["weeks"] == 2

    def test_patient_cannot_schedule_follow_up(self, client, session, patient_user, patient_profile, verified_doctor, clinic_location):
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
        assert resp.status_code == 200
        resp = client.post(f"/api/v1/bookings/{booking.id}/follow-up", json={"weeks": 2})
        assert resp.status_code == 403

    def test_disabled_feature_flag_blocks_route(self, client, session, patient_profile, verified_doctor, clinic_location):
        feature_flag_service.set_enabled(session, key=feature_flag_service.FOLLOWUP, enabled=False)
        booking = _confirmed_booking(session, patient_profile, verified_doctor, clinic_location)
        _login_doctor(client)
        resp = client.post(f"/api/v1/bookings/{booking.id}/follow-up", json={"weeks": 2})
        assert resp.status_code == 403
