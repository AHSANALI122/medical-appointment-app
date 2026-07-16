"""F20 — waitlist: FIFO join, hold promotion on cancellation, 15-min TTL,
exemption from the F18 draft-abuse guard (system-created holds), and
expiry cascading to the next person in line.
"""

from datetime import timedelta

from sqlmodel import select

from app.core.exceptions import PolicyViolationError
from app.core.timezone import now_utc
from app.jobs.expiry_sweep import sweep_expired_bookings
from app.models.booking import Booking
from app.models.enums import BookingSource, BookingStatus, WaitlistStatus
from app.services import booking_service, feature_flag_service, waitlist_service
from app.services.state_machine import (
    MAX_ACTIVE_DRAFTS_PER_PROFILE,
    WAITLIST_HOLD_TTL,
    BookingStateMachine,
)
from tests.conftest import future_slot_time, make_patient


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def _held_slot(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=180):
    """Creates and confirms a booking so the slot is genuinely held —
    the precondition for a valid waitlist join."""
    start, end = future_slot_time(minutes_ahead)
    booking = booking_service.create_draft_booking(
        session, patient_profile=patient_profile, doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id, start_time_utc=start, end_time_utc=end,
    )
    machine = BookingStateMachine(session)
    machine.confirm(booking)
    return booking


class TestJoinWaitlist:
    def test_cannot_join_an_open_slot(self, session, patient_profile, verified_doctor, clinic_location):
        start, end = future_slot_time(60)
        try:
            waitlist_service.join_waitlist(
                session, patient_profile=patient_profile, doctor_id=verified_doctor.id,
                clinic_location_id=clinic_location.id, start_time_utc=start, end_time_utc=end,
            )
            raise AssertionError("expected PolicyViolationError")
        except PolicyViolationError:
            pass

    def test_fifo_positions_assigned_in_join_order(self, session, verified_doctor, clinic_location):
        booking = _held_slot(session, make_patient(session, "waitlist-owner@example.com"), verified_doctor, clinic_location)
        patient_b = make_patient(session, "waitlist-b@example.com")
        patient_c = make_patient(session, "waitlist-c@example.com")

        entry_b = waitlist_service.join_waitlist(
            session, patient_profile=patient_b, doctor_id=verified_doctor.id, clinic_location_id=clinic_location.id,
            start_time_utc=booking.start_time_utc, end_time_utc=booking.end_time_utc,
        )
        entry_c = waitlist_service.join_waitlist(
            session, patient_profile=patient_c, doctor_id=verified_doctor.id, clinic_location_id=clinic_location.id,
            start_time_utc=booking.start_time_utc, end_time_utc=booking.end_time_utc,
        )
        assert entry_b.position == 1
        assert entry_c.position == 2

    def test_joining_twice_returns_same_entry(self, session, patient_profile, verified_doctor, clinic_location):
        owner = make_patient(session, "waitlist-owner2@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)

        first = waitlist_service.join_waitlist(
            session, patient_profile=patient_profile, doctor_id=verified_doctor.id, clinic_location_id=clinic_location.id,
            start_time_utc=booking.start_time_utc, end_time_utc=booking.end_time_utc,
        )
        second = waitlist_service.join_waitlist(
            session, patient_profile=patient_profile, doctor_id=verified_doctor.id, clinic_location_id=clinic_location.id,
            start_time_utc=booking.start_time_utc, end_time_utc=booking.end_time_utc,
        )
        assert first.id == second.id


class TestPromotionOnCancellation:
    def test_patient_cancel_promotes_next_in_line_with_15min_hold(
        self, session, verified_doctor, clinic_location
    ):
        owner = make_patient(session, "cancel-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location, minutes_ahead=180)

        waiting_patient = make_patient(session, "cancel-waiter@example.com")
        entry = waitlist_service.join_waitlist(
            session, patient_profile=waiting_patient, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )

        booking_service.patient_cancel_booking(
            session, booking_id=booking.id, patient_profile=owner, reason="can't make it"
        )

        session.refresh(entry)
        assert entry.status == WaitlistStatus.HOLDING
        assert entry.hold_booking_id is not None

        hold = session.get(Booking, entry.hold_booking_id)
        assert hold.status == BookingStatus.DRAFT
        assert hold.source == BookingSource.SYSTEM_WAITLIST
        assert hold.patient_profile_id == waiting_patient.id

        remaining = hold.expires_at - now_utc()
        assert timedelta(minutes=14) < remaining <= WAITLIST_HOLD_TTL

    def test_hold_exempt_from_draft_abuse_guard(self, session, verified_doctor, clinic_location, specialization):
        """A patient who already has the maximum number of active
        user-initiated drafts must still receive their waitlist hold — the
        hold uses source=system_waitlist, which the abuse guard skips."""
        waiting_patient = make_patient(session, "exempt-waiter@example.com")

        # Max out this patient's *other* active drafts with unrelated doctors.
        for i in range(MAX_ACTIVE_DRAFTS_PER_PROFILE):
            from tests.agents.test_agent_tools import _make_verified_doctor

            other_doctor, other_location = _make_verified_doctor(session, specialization, email=f"filler-{i}@example.com")
            start, end = future_slot_time(500 + i * 60)
            booking_service.create_draft_booking(
                session, patient_profile=waiting_patient, doctor_id=other_doctor.id,
                clinic_location_id=other_location.id, start_time_utc=start, end_time_utc=end,
            )

        owner = make_patient(session, "exempt-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)
        entry = waitlist_service.join_waitlist(
            session, patient_profile=waiting_patient, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )

        booking_service.patient_cancel_booking(session, booking_id=booking.id, patient_profile=owner, reason="x")

        session.refresh(entry)
        assert entry.status == WaitlistStatus.HOLDING

    def test_expired_hold_cascades_to_next_in_line(self, session, verified_doctor, clinic_location):
        owner = make_patient(session, "cascade-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)

        first_in_line = make_patient(session, "cascade-first@example.com")
        second_in_line = make_patient(session, "cascade-second@example.com")
        entry_first = waitlist_service.join_waitlist(
            session, patient_profile=first_in_line, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )
        entry_second = waitlist_service.join_waitlist(
            session, patient_profile=second_in_line, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )

        booking_service.patient_cancel_booking(session, booking_id=booking.id, patient_profile=owner, reason="x")
        session.refresh(entry_first)
        first_hold = session.get(Booking, entry_first.hold_booking_id)

        # Force the first hold to expire and run the sweep.
        first_hold.expires_at = now_utc() - timedelta(seconds=1)
        session.add(first_hold)
        session.commit()
        sweep_expired_bookings(session)

        session.refresh(entry_first)
        session.refresh(entry_second)
        assert entry_first.status == WaitlistStatus.EXPIRED
        assert entry_second.status == WaitlistStatus.HOLDING
        assert entry_second.hold_booking_id is not None

    def test_confirming_hold_marks_waitlist_entry_booked(self, client, session, patient_user, verified_doctor, clinic_location):
        owner = make_patient(session, "confirm-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)

        from app.models.user import PatientProfile

        waiting_profile = session.exec(select(PatientProfile).where(PatientProfile.user_id == patient_user.id)).one()
        entry = waitlist_service.join_waitlist(
            session, patient_profile=waiting_profile, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )
        booking_service.patient_cancel_booking(session, booking_id=booking.id, patient_profile=owner, reason="x")
        session.refresh(entry)

        _login_patient(client, patient_user)
        resp = client.post(f"/api/v1/bookings/{entry.hold_booking_id}/confirm")
        assert resp.status_code == 200

        session.refresh(entry)
        assert entry.status == WaitlistStatus.BOOKED


class TestLeaveWaitlist:
    def test_leave_a_waiting_entry(self, session, patient_profile, verified_doctor, clinic_location):
        owner = make_patient(session, "leave-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)
        entry = waitlist_service.join_waitlist(
            session, patient_profile=patient_profile, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )
        left = waitlist_service.leave_waitlist(session, patient_profile=patient_profile, waitlist_id=entry.id)
        assert left.status == WaitlistStatus.CANCELLED

    def test_cannot_leave_a_holding_entry(self, session, verified_doctor, clinic_location):
        owner = make_patient(session, "leave-owner2@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)
        waiting_patient = make_patient(session, "leave-waiter2@example.com")
        entry = waitlist_service.join_waitlist(
            session, patient_profile=waiting_patient, doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id, start_time_utc=booking.start_time_utc,
            end_time_utc=booking.end_time_utc,
        )
        booking_service.patient_cancel_booking(session, booking_id=booking.id, patient_profile=owner, reason="x")
        session.refresh(entry)
        assert entry.status == WaitlistStatus.HOLDING

        try:
            waitlist_service.leave_waitlist(session, patient_profile=waiting_patient, waitlist_id=entry.id)
            raise AssertionError("expected PolicyViolationError")
        except PolicyViolationError:
            pass


class TestWaitlistRouter:
    def test_join_list_and_leave_via_api(self, client, session, patient_user, verified_doctor, clinic_location):
        owner = make_patient(session, "api-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)

        _login_patient(client, patient_user)
        join_resp = client.post(
            "/api/v1/waitlist",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": booking.start_time_utc.isoformat(),
                "end_time_utc": booking.end_time_utc.isoformat(),
            },
        )
        assert join_resp.status_code == 201
        entry_id = join_resp.json()["id"]

        list_resp = client.get("/api/v1/waitlist/me")
        assert list_resp.status_code == 200
        assert any(e["id"] == entry_id for e in list_resp.json())

        leave_resp = client.delete(f"/api/v1/waitlist/{entry_id}")
        assert leave_resp.status_code == 200
        assert leave_resp.json()["status"] == "cancelled"

    def test_disabled_feature_flag_blocks_waitlist_routes(
        self, client, session, patient_user, verified_doctor, clinic_location
    ):
        feature_flag_service.set_enabled(session, key=feature_flag_service.WAITLIST, enabled=False)
        owner = make_patient(session, "flagged-owner@example.com")
        booking = _held_slot(session, owner, verified_doctor, clinic_location)

        _login_patient(client, patient_user)
        resp = client.post(
            "/api/v1/waitlist",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": booking.start_time_utc.isoformat(),
                "end_time_utc": booking.end_time_utc.isoformat(),
            },
        )
        assert resp.status_code == 403
