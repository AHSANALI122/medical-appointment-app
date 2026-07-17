from datetime import timedelta

from sqlalchemy import text

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


def _to_confirmed(session, booking_id: str) -> Booking:
    machine = BookingStateMachine(session)
    booking = session.get(Booking, booking_id)
    booking = machine.confirm(booking)
    booking = machine.doctor_accept(booking)
    return booking


class TestPatientOwnHistory:
    def test_profile_id_must_be_a_real_owned_profile(self, client_factory, patient_user):
        client = client_factory()
        _login_patient(client, patient_user)

        # patient_user.id is a User id, not a PatientProfile id — resolve_owned_patient_profile
        # must reject it rather than silently resolving to the caller's own profile.
        write_resp = client.put(
            f"/api/v1/patient-profiles/{patient_user.id}/medical-history",
            json={"blood_group": "O+", "allergies": "penicillin"},
        )
        assert write_resp.status_code == 403

    def test_write_then_read_own_history(
        self, client_factory, patient_user, patient_profile
    ):
        client = client_factory()
        _login_patient(client, patient_user)

        write_resp = client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "O+", "allergies": "penicillin", "chronic_conditions": "asthma"},
        )
        assert write_resp.status_code == 200
        body = write_resp.json()
        assert body["version"] == 1
        assert body["blood_group"] == "O+"
        assert body["allergies"] == "penicillin"

        read_resp = client.get(f"/api/v1/patient-profiles/{patient_profile.id}/medical-history")
        assert read_resp.status_code == 200
        assert read_resp.json()["chronic_conditions"] == "asthma"

    def test_edit_appends_new_version_not_overwrite(
        self, client_factory, patient_user, patient_profile
    ):
        client = client_factory()
        _login_patient(client, patient_user)

        client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "A+"},
        )
        client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "A+", "medications": "metformin"},
        )

        current = client.get(f"/api/v1/patient-profiles/{patient_profile.id}/medical-history")
        assert current.json()["version"] == 2
        assert current.json()["medications"] == "metformin"

        versions = client.get(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history/versions"
        )
        assert versions.status_code == 200
        payload = versions.json()
        assert [v["version"] for v in payload] == [2, 1]
        assert payload[1]["medications"] is None  # first version predates the edit

    def test_other_patient_cannot_access(self, client_factory, patient_profile):
        intruder = client_factory()
        intruder.post(
            "/api/v1/auth/register/patient",
            json={"email": "mh-intruder@example.com", "password": "password123", "full_name": "Intruder"},
        )
        resp = intruder.get(f"/api/v1/patient-profiles/{patient_profile.id}/medical-history")
        assert resp.status_code == 403

    def test_encrypted_at_rest(self, client_factory, session, patient_user, patient_profile):
        client = client_factory()
        _login_patient(client, patient_user)
        secret = "severe shellfish allergy"
        client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"allergies": secret},
        )
        raw = session.exec(
            text("SELECT allergies FROM medical_histories WHERE patient_profile_id = CAST(:pid AS uuid)").bindparams(
                pid=str(patient_profile.id)
            )
        ).one()
        assert secret not in raw[0]


class TestDoctorAccessWindow:
    def test_doctor_with_confirmed_booking_can_read(
        self, client_factory, session, patient_user, patient_profile, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        patient_client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "B+", "allergies": "none"},
        )
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _to_confirmed(session, booking["id"])

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get(f"/api/v1/bookings/{booking['id']}/medical-history")
        assert resp.status_code == 200
        assert resp.json()["blood_group"] == "B+"

    def test_doctor_with_only_cancelled_booking_gets_403(
        self, client_factory, session, patient_user, patient_profile, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        patient_client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "AB-"},
        )
        booking = _create_draft(patient_client, verified_doctor, clinic_location, minutes_ahead=200)
        machine = BookingStateMachine(session)
        b = session.get(Booking, booking["id"])
        b = machine.confirm(b)
        machine.cancel(b, cancelled_by="patient", reason="changed my mind", cancellation_policy_hours=2)

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get(f"/api/v1/bookings/{booking['id']}/medical-history")
        assert resp.status_code == 403

    def test_doctor_with_rejected_booking_gets_403(
        self, client_factory, session, patient_user, patient_profile, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        patient_client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "AB-"},
        )
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        machine = BookingStateMachine(session)
        b = session.get(Booking, booking["id"])
        machine.confirm(b)
        b = session.get(Booking, booking["id"])
        machine.doctor_reject(b, reason="unavailable")

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get(f"/api/v1/bookings/{booking['id']}/medical-history")
        assert resp.status_code == 403

    def test_doctor_with_stale_completed_booking_gets_403(
        self, client_factory, session, patient_user, patient_profile, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        patient_client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "O-"},
        )
        booking = _create_draft(patient_client, verified_doctor, clinic_location, minutes_ahead=35)
        machine = BookingStateMachine(session)
        b = session.get(Booking, booking["id"])
        b = machine.confirm(b)
        b = machine.doctor_accept(b)
        # Push the appointment (and therefore the access window) more than a
        # year into the past, then complete it — this is the "stale" case the
        # F24 acceptance criterion targets, distinct from cancelled/rejected.
        b.start_time_utc = now_utc() - timedelta(days=400)
        b.end_time_utc = b.start_time_utc + timedelta(minutes=30)
        session.add(b)
        session.commit()
        machine.mark_completed(b)

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get(f"/api/v1/bookings/{booking['id']}/medical-history")
        assert resp.status_code == 403

    def test_unrelated_doctor_gets_404_on_someone_elses_booking(
        self,
        client_factory,
        session,
        patient_user,
        patient_profile,
        verified_doctor,
        clinic_location,
        specialization,
    ):
        from app.core.security import hash_password
        from app.models.doctor import DoctorProfile
        from app.models.enums import DoctorVerificationStatus, UserRole
        from app.models.user import User

        other_doctor_user = User(
            email="otherdoc-mh@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Other MH",
        )
        session.add(other_doctor_user)
        session.flush()
        session.add(
            DoctorProfile(
                user_id=other_doctor_user.id,
                specialization_id=specialization.id,
                pmc_number="PMC-777",
                consultation_fee=1000,
                verification_status=DoctorVerificationStatus.VERIFIED,
            )
        )
        session.commit()

        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _to_confirmed(session, booking["id"])

        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc-mh@example.com")
        resp = other_doctor_client.get(f"/api/v1/bookings/{booking['id']}/medical-history")
        assert resp.status_code == 404

    def test_doctor_read_is_audit_logged(
        self, client_factory, session, patient_user, patient_profile, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        patient_client.put(
            f"/api/v1/patient-profiles/{patient_profile.id}/medical-history",
            json={"blood_group": "B+"},
        )
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        _to_confirmed(session, booking["id"])

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        doctor_client.get(f"/api/v1/bookings/{booking['id']}/medical-history")

        logs = session.exec(
            text("SELECT action, resource_type FROM audit_logs WHERE resource_type = 'medical_history'")
        ).all()
        assert any(row[0] == "read" for row in logs)
