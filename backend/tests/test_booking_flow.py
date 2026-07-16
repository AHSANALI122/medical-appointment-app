from datetime import timedelta

from app.core.timezone import now_utc


def _login_patient(client, session, patient_user):
    resp = client.post(
        "/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"}
    )
    assert resp.status_code == 200


def _login_doctor(client, verified_doctor_user_email="doctor@example.com"):
    resp = client.post(
        "/api/v1/auth/login", json={"email": verified_doctor_user_email, "password": "password123"}
    )
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
    return resp


class TestFullBookingLifecycle:
    def test_full_happy_path(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)

        draft_resp = _create_draft(patient_client, verified_doctor, clinic_location)
        assert draft_resp.status_code == 201
        draft = draft_resp.json()
        assert draft["status"] == "draft"
        assert draft["fee_charged"] == verified_doctor.consultation_fee
        assert draft["expires_at"] is not None

        confirm_resp = patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == "pending"

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        accept_resp = doctor_client.post(f"/api/v1/bookings/{draft['id']}/accept")
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == "confirmed"
        assert accept_resp.json()["confirmed_at"] is not None

    def test_doctor_reject_flow(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(patient_client, verified_doctor, clinic_location).json()
        patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.post(
            f"/api/v1/bookings/{draft['id']}/reject", json={"reason": "fully booked that day"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        assert resp.json()["rejected_reason"] == "fully booked that day"

    def test_patient_cancel_within_policy_window_blocked(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(patient_client, verified_doctor, clinic_location, minutes_ahead=90).json()
        patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        doctor_client.post(f"/api/v1/bookings/{draft['id']}/accept")

        resp = patient_client.post(
            f"/api/v1/bookings/{draft['id']}/cancel", json={"reason": "too soon"}
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "policy_violation"

    def test_patient_cancel_outside_policy_window_allowed(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(
            patient_client, verified_doctor, clinic_location, minutes_ahead=60 * 5
        ).json()
        patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        doctor_client.post(f"/api/v1/bookings/{draft['id']}/accept")

        resp = patient_client.post(
            f"/api/v1/bookings/{draft['id']}/cancel", json={"reason": "plans changed"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert resp.json()["cancelled_by"] == "patient"

    def test_fee_snapshot_immutable_after_doctor_changes_fee(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(patient_client, verified_doctor, clinic_location).json()
        original_fee = draft["fee_charged"]

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        doctor_client.patch("/api/v1/doctors/me", json={"consultation_fee": original_fee + 1000})

        patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")
        accept_resp = doctor_client.post(f"/api/v1/bookings/{draft['id']}/accept")
        assert accept_resp.json()["fee_charged"] == original_fee

    def test_unverified_doctor_cannot_receive_draft(self, client_factory, session, specialization):
        from app.core.security import hash_password
        from app.models.doctor import ClinicLocation, DoctorProfile
        from app.models.enums import DoctorVerificationStatus, UserRole
        from app.models.user import User

        user = User(
            email="unverified@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Unverified",
        )
        session.add(user)
        session.flush()
        doctor = DoctorProfile(
            user_id=user.id,
            specialization_id=specialization.id,
            pmc_number="PMC-000",
            consultation_fee=1000,
            verification_status=DoctorVerificationStatus.UNVERIFIED,
        )
        session.add(doctor)
        session.commit()
        session.refresh(doctor)
        location = ClinicLocation(doctor_id=doctor.id, name="Clinic", address="addr", city="Lahore")
        session.add(location)
        session.commit()
        session.refresh(location)

        patient_client = client_factory()
        patient_client.post(
            "/api/v1/auth/register/patient",
            json={"email": "blocked@example.com", "password": "password123", "full_name": "Blocked"},
        )
        resp = _create_draft(patient_client, doctor, location)
        assert resp.status_code == 403

    def test_doctor_cannot_act_on_another_doctors_booking(
        self, client_factory, session, patient_user, verified_doctor, clinic_location, specialization
    ):
        from app.core.security import hash_password
        from app.models.enums import UserRole
        from app.models.user import User

        other_doctor_user = User(
            email="otherdoc@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Other",
        )
        session.add(other_doctor_user)
        session.flush()
        from app.models.doctor import DoctorProfile
        from app.models.enums import DoctorVerificationStatus

        other_doctor = DoctorProfile(
            user_id=other_doctor_user.id,
            specialization_id=specialization.id,
            pmc_number="PMC-777",
            consultation_fee=1000,
            verification_status=DoctorVerificationStatus.VERIFIED,
        )
        session.add(other_doctor)
        session.commit()

        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(patient_client, verified_doctor, clinic_location).json()
        patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")

        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc@example.com")
        resp = other_doctor_client.post(f"/api/v1/bookings/{draft['id']}/accept")
        assert resp.status_code == 404

    def test_patient_cannot_access_another_patients_booking(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(patient_client, verified_doctor, clinic_location).json()

        other_client = client_factory()
        other_client.post(
            "/api/v1/auth/register/patient",
            json={"email": "intruder@example.com", "password": "password123", "full_name": "Intruder"},
        )
        resp = other_client.get(f"/api/v1/bookings/{draft['id']}")
        assert resp.status_code == 403

    def test_no_optimistic_state_double_confirm_is_rejected(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, session, patient_user)
        draft = _create_draft(patient_client, verified_doctor, clinic_location).json()

        first = patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")
        assert first.status_code == 200
        second = patient_client.post(f"/api/v1/bookings/{draft['id']}/confirm")
        assert second.status_code == 422
        assert second.json()["error_code"] == "policy_violation"
