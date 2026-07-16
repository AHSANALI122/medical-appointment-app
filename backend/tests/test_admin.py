from datetime import timedelta

import pytest

from app.core.security import hash_password
from app.core.timezone import now_utc
from app.models.enums import BookingStatus, UserRole
from app.models.user import User
from app.services.state_machine import BookingStateMachine


def _login(client, email, password="password123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200


def _register_admin(session, email="admin@example.com") -> User:
    user = User(
        email=email, password_hash=hash_password("password123"), role=UserRole.ADMIN, full_name="Admin User"
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _unverified_doctor(session, specialization, email="pending-doc@example.com"):
    from app.models.doctor import DoctorProfile
    from app.models.enums import DoctorVerificationStatus

    user = User(
        email=email, password_hash=hash_password("password123"), role=UserRole.DOCTOR, full_name="Dr. Pending"
    )
    session.add(user)
    session.flush()
    doctor = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization.id,
        pmc_number="PMC-000",
        consultation_fee=1200,
        verification_status=DoctorVerificationStatus.UNVERIFIED,
    )
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return doctor


ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/doctors/pending"),
    ("GET", "/api/v1/admin/bookings"),
    ("GET", "/api/v1/admin/reviews/pending"),
    ("GET", "/api/v1/admin/stats"),
]


class TestAdminAccessControl:
    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_patient_gets_403(self, client_factory, patient_user, method, path):
        client = client_factory()
        _login(client, patient_user.email)
        resp = client.request(method, path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_doctor_gets_403(self, client_factory, verified_doctor, method, path):
        client = client_factory()
        _login(client, "doctor@example.com")
        resp = client.request(method, path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_unauthenticated_gets_401(self, client_factory, method, path):
        client = client_factory()
        resp = client.request(method, path)
        assert resp.status_code == 401

    def test_admin_can_access(self, client_factory, session):
        admin_user = _register_admin(session)
        client = client_factory()
        _login(client, admin_user.email)
        resp = client.get("/api/v1/admin/stats")
        assert resp.status_code == 200


class TestDoctorVerificationQueue:
    def test_verify_doctor_makes_them_searchable(self, client_factory, session, specialization):
        doctor = _unverified_doctor(session, specialization)
        admin_user = _register_admin(session)
        admin_client = client_factory()
        _login(admin_client, admin_user.email)

        pending_resp = admin_client.get("/api/v1/admin/doctors/pending")
        assert pending_resp.status_code == 200
        assert str(doctor.id) in {d["id"] for d in pending_resp.json()["items"]}

        verify_resp = admin_client.post(
            f"/api/v1/admin/doctors/{doctor.id}/verify", json={"status": "verified"}
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["verification_status"] == "verified"

        search_resp = admin_client.get("/api/v1/doctors")
        assert str(doctor.id) in {d["id"] for d in search_resp.json()["items"]}

    def test_reject_doctor_with_reason(self, client_factory, session, specialization):
        doctor = _unverified_doctor(session, specialization, email="reject-doc@example.com")
        admin_user = _register_admin(session, email="admin2@example.com")
        admin_client = client_factory()
        _login(admin_client, admin_user.email)

        resp = admin_client.post(
            f"/api/v1/admin/doctors/{doctor.id}/verify",
            json={"status": "rejected", "reason": "PMC number not found"},
        )
        assert resp.status_code == 200
        assert resp.json()["verification_status"] == "rejected"


class TestBookingOversightAndCorrection:
    def test_correct_no_show_to_completed_within_window(
        self, client_factory, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=now_utc() - timedelta(hours=1),
            end_time_utc=now_utc() - timedelta(minutes=30),
            fee_charged=verified_doctor.consultation_fee,
            address_snapshot="Test Clinic",
        )
        booking.status = BookingStatus.CONFIRMED
        session.add(booking)
        session.commit()
        booking = machine.mark_no_show(booking)

        admin_user = _register_admin(session, email="admin3@example.com")
        admin_client = client_factory()
        _login(admin_client, admin_user.email)

        resp = admin_client.post(
            f"/api/v1/admin/bookings/{booking.id}/correct-completion", json={"target": "completed"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_oversight_lists_bookings_across_patients(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login(patient_client, patient_user.email)
        start = now_utc() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        patient_client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": start.isoformat(),
                "end_time_utc": end.isoformat(),
            },
        )

        admin_user = _register_admin(session, email="admin4@example.com")
        admin_client = client_factory()
        _login(admin_client, admin_user.email)
        resp = admin_client.get("/api/v1/admin/bookings")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1


class TestReviewModeration:
    def test_moderate_pending_review_to_approved(
        self, client_factory, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=now_utc() + timedelta(hours=1),
            end_time_utc=now_utc() + timedelta(hours=1, minutes=30),
            fee_charged=verified_doctor.consultation_fee,
            address_snapshot="Test Clinic",
        )
        booking = machine.confirm(booking)
        booking = machine.doctor_accept(booking)
        booking = machine.mark_completed(booking)

        from app.services import review_service

        review = review_service.create_review(
            session, booking_id=booking.id, patient_profile=patient_profile, rating=5, comment="Great"
        )

        admin_user = _register_admin(session, email="admin5@example.com")
        admin_client = client_factory()
        _login(admin_client, admin_user.email)

        pending_resp = admin_client.get("/api/v1/admin/reviews/pending")
        assert str(review.id) in {r["id"] for r in pending_resp.json()["items"]}

        moderate_resp = admin_client.post(
            f"/api/v1/admin/reviews/{review.id}/moderate", json={"status": "approved"}
        )
        assert moderate_resp.status_code == 200
        assert moderate_resp.json()["moderation_status"] == "approved"
