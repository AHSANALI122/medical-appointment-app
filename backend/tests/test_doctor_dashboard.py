from datetime import timedelta

from app.core.security import hash_password
from app.core.timezone import now_utc
from app.models.doctor import DoctorProfile
from app.models.enums import DoctorVerificationStatus, UserRole
from app.models.user import User


def _login_doctor(client, email="doctor@example.com"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location, minutes_ahead=60):
    start = now_utc() + timedelta(minutes=minutes_ahead)
    end = start + timedelta(minutes=30)
    resp = patient_client.post(
        "/api/v1/bookings",
        json={
            "doctor_id": str(verified_doctor.id),
            "clinic_location_id": str(clinic_location.id),
            "start_time_utc": start.isoformat(),
            "end_time_utc": end.isoformat(),
        },
    )
    assert resp.status_code == 201
    booking = resp.json()
    patient_client.post(f"/api/v1/bookings/{booking['id']}/confirm")

    doctor_client = client_factory()
    _login_doctor(doctor_client)
    accept_resp = doctor_client.post(f"/api/v1/bookings/{booking['id']}/accept")
    assert accept_resp.status_code == 200
    return booking


def _other_doctor(session, specialization, email="otherdoc-dash@example.com"):
    user = User(
        email=email, password_hash=hash_password("password123"), role=UserRole.DOCTOR, full_name="Dr. Other"
    )
    session.add(user)
    session.flush()
    doctor = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization.id,
        pmc_number="PMC-999",
        consultation_fee=1000,
        verification_status=DoctorVerificationStatus.VERIFIED,
    )
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return doctor


class TestDoctorBookingRowLevelAuth:
    def test_doctor_a_requesting_doctor_b_booking_returns_403(
        self, client_factory, session, patient_user, verified_doctor, clinic_location, specialization
    ):
        """F13 acceptance: doctor A requesting doctor B's booking gets 403."""
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location)

        _other_doctor(session, specialization)
        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc-dash@example.com")

        resp = other_doctor_client.get(f"/api/v1/bookings/doctor/{booking['id']}")
        assert resp.status_code == 403

    def test_owning_doctor_can_read_booking(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location)

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get(f"/api/v1/bookings/doctor/{booking['id']}")
        assert resp.status_code == 200

    def test_nonexistent_booking_returns_404(self, client_factory, session, verified_doctor):
        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get("/api/v1/bookings/doctor/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestDoctorDashboard:
    def test_dashboard_groups_pending_and_confirmed(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)

        # One confirmed booking, one still pending.
        confirmed = _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location)

        start = now_utc() + timedelta(hours=5)
        end = start + timedelta(minutes=30)
        draft_resp = patient_client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": start.isoformat(),
                "end_time_utc": end.isoformat(),
            },
        )
        pending_booking = draft_resp.json()
        patient_client.post(f"/api/v1/bookings/{pending_booking['id']}/confirm")

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get("/api/v1/bookings/doctor/dashboard")
        assert resp.status_code == 200
        body = resp.json()

        pending_ids = {b["id"] for b in body["pending"]}
        assert pending_booking["id"] in pending_ids
        assert confirmed["id"] not in pending_ids

        confirmed_ids = {b["id"] for b in body["today"] + body["upcoming"]}
        assert confirmed["id"] in confirmed_ids


class TestAvailabilityEditing:
    def test_doctor_can_deactivate_availability_rule(
        self, client_factory, verified_doctor, availability_rule
    ):
        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.patch(
            f"/api/v1/doctors/me/availability-rules/{availability_rule.id}", json={"is_active": False}
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_doctor_cannot_edit_another_doctors_rule(
        self, client_factory, session, availability_rule, specialization
    ):
        _other_doctor(session, specialization)
        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc-dash@example.com")
        resp = other_doctor_client.patch(
            f"/api/v1/doctors/me/availability-rules/{availability_rule.id}", json={"is_active": False}
        )
        assert resp.status_code == 404

    def test_doctor_can_delete_leave_exception(self, client_factory, verified_doctor):
        doctor_client = client_factory()
        _login_doctor(doctor_client)
        create_resp = doctor_client.post(
            "/api/v1/doctors/me/availability-exceptions",
            json={"exception_date": "2026-08-01", "reason": "leave"},
        )
        assert create_resp.status_code == 201
        exception_id = create_resp.json()["id"]

        delete_resp = doctor_client.delete(f"/api/v1/doctors/me/availability-exceptions/{exception_id}")
        assert delete_resp.status_code == 204

        list_resp = doctor_client.get("/api/v1/doctors/me/availability-exceptions")
        assert exception_id not in {e["id"] for e in list_resp.json()}
