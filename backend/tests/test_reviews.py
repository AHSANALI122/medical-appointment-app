from datetime import timedelta

from app.core.timezone import now_utc
from app.models.booking import Booking
from app.services.state_machine import BookingStateMachine


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def _login_doctor(client, email="doctor@example.com"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200


def _create_draft(client, verified_doctor, clinic_location, minutes_ahead=60):
    start = now_utc() + timedelta(minutes=minutes_ahead)
    end = start + timedelta(minutes=30)
    resp = client.post(
        "/api/v1/bookings",
        json={
            "doctor_id": str(verified_doctor.id),
            "clinic_location_id": str(clinic_location.id),
            "start_time_utc": start.isoformat(),
            "end_time_utc": end.isoformat(),
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _to_completed(session, booking_id: str) -> Booking:
    machine = BookingStateMachine(session)
    booking = session.get(Booking, booking_id)
    booking = machine.confirm(booking)  # draft -> pending would normally be a separate call
    return booking


def _drive_to_completed(session, booking_id: str) -> Booking:
    """Test-only shortcut: pushes a fresh draft all the way to completed via
    direct state-machine calls, mirroring test_state_machine.py's pattern —
    there is no HTTP endpoint yet for the auto-complete job's transition."""
    machine = BookingStateMachine(session)
    booking = session.get(Booking, booking_id)
    booking = machine.confirm(booking)
    booking = machine.doctor_accept(booking)
    booking = machine.mark_completed(booking)
    return booking


class TestCreateReview:
    def test_review_on_completed_booking_succeeds(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])

        resp = patient_client.post(
            f"/api/v1/bookings/{booking['id']}/review", json={"rating": 5, "comment": "Great doctor"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rating"] == 5
        assert body["moderation_status"] == "pending"

    def test_review_on_pending_booking_returns_403(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        """F11 acceptance: a non-completed booking review attempt returns 403."""
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _to_completed(session, booking["id"])  # only reaches `pending`, not `completed`

        resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 4})
        assert resp.status_code == 403

    def test_review_on_cancelled_booking_returns_403(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location, minutes_ahead=200)
        machine = BookingStateMachine(session)
        b = session.get(Booking, booking["id"])
        b = machine.confirm(b)
        machine.cancel(b, cancelled_by="patient", reason="changed my mind", cancellation_policy_hours=2)

        resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 3})
        assert resp.status_code == 403

    def test_review_on_no_show_booking_returns_403(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location, minutes_ahead=35)
        machine = BookingStateMachine(session)
        b = session.get(Booking, booking["id"])
        b = machine.confirm(b)
        b = machine.doctor_accept(b)
        b.start_time_utc = now_utc() - timedelta(minutes=5)
        session.add(b)
        session.commit()
        machine.mark_no_show(b)

        resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 1})
        assert resp.status_code == 403

    def test_duplicate_review_rejected(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])

        first = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 5})
        assert first.status_code == 201
        second = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 2})
        assert second.status_code == 422

    def test_review_window_expired(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        b = _drive_to_completed(session, booking["id"])
        b.completed_at = now_utc() - timedelta(days=31)
        session.add(b)
        session.commit()

        resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 5})
        assert resp.status_code == 422

    def test_other_patient_cannot_review_someone_elses_booking(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])

        intruder_client = client_factory()
        intruder_client.post(
            "/api/v1/auth/register/patient",
            json={"email": "review-intruder@example.com", "password": "password123", "full_name": "Intruder"},
        )
        resp = intruder_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 1})
        assert resp.status_code == 404

    def test_invalid_rating_rejected(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])

        resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 6})
        assert resp.status_code == 422


class TestReviewVisibilityAndReply:
    def test_pending_review_not_publicly_visible(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])
        patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 5})

        resp = patient_client.get(f"/api/v1/doctors/{verified_doctor.id}/reviews")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_approved_review_visible_and_counts_toward_rating(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        from app.models.enums import ReviewModerationStatus
        from app.models.review import Review

        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])
        create_resp = patient_client.post(
            f"/api/v1/bookings/{booking['id']}/review", json={"rating": 4, "comment": "Good"}
        )
        review_id = create_resp.json()["id"]

        review = session.get(Review, review_id)
        review.moderation_status = ReviewModerationStatus.APPROVED
        session.add(review)
        session.commit()

        list_resp = patient_client.get(f"/api/v1/doctors/{verified_doctor.id}/reviews")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1

        profile_resp = patient_client.get(f"/api/v1/doctors/{verified_doctor.id}")
        assert profile_resp.json()["average_rating"] == 4.0
        assert profile_resp.json()["review_count"] == 1

    def test_doctor_can_reply_once(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])
        create_resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 5})
        review_id = create_resp.json()["id"]

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        reply_resp = doctor_client.post(f"/api/v1/reviews/{review_id}/reply", json={"reply": "Thank you!"})
        assert reply_resp.status_code == 200
        assert reply_resp.json()["doctor_reply"] == "Thank you!"

        second_reply = doctor_client.post(f"/api/v1/reviews/{review_id}/reply", json={"reply": "Again"})
        assert second_reply.status_code == 422

    def test_unrelated_doctor_cannot_reply(
        self, client_factory, session, patient_user, verified_doctor, clinic_location, specialization
    ):
        from app.core.security import hash_password
        from app.models.doctor import DoctorProfile
        from app.models.enums import DoctorVerificationStatus, UserRole
        from app.models.user import User

        other_doctor_user = User(
            email="otherdoc-review@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Other Review",
        )
        session.add(other_doctor_user)
        session.flush()
        session.add(
            DoctorProfile(
                user_id=other_doctor_user.id,
                specialization_id=specialization.id,
                pmc_number="PMC-557",
                consultation_fee=1000,
                verification_status=DoctorVerificationStatus.VERIFIED,
            )
        )
        session.commit()

        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _drive_to_completed(session, booking["id"])
        create_resp = patient_client.post(f"/api/v1/bookings/{booking['id']}/review", json={"rating": 5})
        review_id = create_resp.json()["id"]

        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc-review@example.com")
        resp = other_doctor_client.post(f"/api/v1/reviews/{review_id}/reply", json={"reply": "hi"})
        assert resp.status_code == 404
