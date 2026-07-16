from datetime import timedelta

from sqlalchemy import text

from app.core.timezone import now_utc


def _login_patient(client, patient_user):
    resp = client.post(
        "/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"}
    )
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


class TestPatientNote:
    def test_patient_writes_and_reads_own_note(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)

        write_resp = patient_client.put(
            f"/api/v1/bookings/{booking['id']}/patient-note", json={"content": "pait mein dard hai"}
        )
        assert write_resp.status_code == 200
        assert write_resp.json()["content"] == "pait mein dard hai"

        read_resp = patient_client.get(f"/api/v1/bookings/{booking['id']}/patient-note")
        assert read_resp.status_code == 200
        assert read_resp.json()["content"] == "pait mein dard hai"

    def test_treating_doctor_can_read_patient_note(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        patient_client.put(
            f"/api/v1/bookings/{booking['id']}/patient-note", json={"content": "fever for 3 days"}
        )

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        resp = doctor_client.get(f"/api/v1/bookings/{booking['id']}/patient-note")
        assert resp.status_code == 200
        assert resp.json()["content"] == "fever for 3 days"

    def test_unrelated_doctor_cannot_read_patient_note(
        self,
        client_factory,
        session,
        patient_user,
        verified_doctor,
        clinic_location,
        specialization,
    ):
        from app.core.security import hash_password
        from app.models.doctor import DoctorProfile
        from app.models.enums import DoctorVerificationStatus, UserRole
        from app.models.user import User

        other_doctor_user = User(
            email="otherdoc-notes@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Other Notes",
        )
        session.add(other_doctor_user)
        session.flush()
        session.add(
            DoctorProfile(
                user_id=other_doctor_user.id,
                specialization_id=specialization.id,
                pmc_number="PMC-555",
                consultation_fee=1000,
                verification_status=DoctorVerificationStatus.VERIFIED,
            )
        )
        session.commit()

        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        patient_client.put(f"/api/v1/bookings/{booking['id']}/patient-note", json={"content": "secret"})

        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc-notes@example.com")
        resp = other_doctor_client.get(f"/api/v1/bookings/{booking['id']}/patient-note")
        assert resp.status_code == 404

    def test_other_patient_cannot_read_note(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)
        patient_client.put(f"/api/v1/bookings/{booking['id']}/patient-note", json={"content": "secret"})

        intruder_client = client_factory()
        intruder_client.post(
            "/api/v1/auth/register/patient",
            json={"email": "note-intruder@example.com", "password": "password123", "full_name": "Intruder"},
        )
        resp = intruder_client.get(f"/api/v1/bookings/{booking['id']}/patient-note")
        assert resp.status_code == 404


class TestClinicalNote:
    def test_patient_cannot_read_unshared_clinical_note(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        write_resp = doctor_client.put(
            f"/api/v1/bookings/{booking['id']}/clinical-note",
            json={"content": "suspected gastritis, prescribed rest", "is_shared_with_patient": False},
        )
        assert write_resp.status_code == 200
        assert write_resp.json()["is_shared_with_patient"] is False

        # Doctor can always read their own note.
        doctor_read = doctor_client.get(f"/api/v1/bookings/{booking['id']}/clinical-note")
        assert doctor_read.status_code == 200

        # Patient, even authenticated with a valid JWT and owning the booking,
        # is blocked from an unshared clinical note (F6 acceptance criterion).
        patient_read = patient_client.get(f"/api/v1/bookings/{booking['id']}/clinical-note")
        assert patient_read.status_code == 403

    def test_patient_can_read_clinical_note_once_shared(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        doctor_client.put(
            f"/api/v1/bookings/{booking['id']}/clinical-note",
            json={"content": "follow up in 2 weeks", "is_shared_with_patient": True},
        )

        resp = patient_client.get(f"/api/v1/bookings/{booking['id']}/clinical-note")
        assert resp.status_code == 200
        assert resp.json()["content"] == "follow up in 2 weeks"

    def test_unrelated_doctor_cannot_write_clinical_note(
        self,
        client_factory,
        session,
        patient_user,
        verified_doctor,
        clinic_location,
        specialization,
    ):
        from app.core.security import hash_password
        from app.models.doctor import DoctorProfile
        from app.models.enums import DoctorVerificationStatus, UserRole
        from app.models.user import User

        other_doctor_user = User(
            email="otherdoc-clinical@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. Other Clinical",
        )
        session.add(other_doctor_user)
        session.flush()
        session.add(
            DoctorProfile(
                user_id=other_doctor_user.id,
                specialization_id=specialization.id,
                pmc_number="PMC-556",
                consultation_fee=1000,
                verification_status=DoctorVerificationStatus.VERIFIED,
            )
        )
        session.commit()

        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)

        other_doctor_client = client_factory()
        _login_doctor(other_doctor_client, "otherdoc-clinical@example.com")
        resp = other_doctor_client.put(
            f"/api/v1/bookings/{booking['id']}/clinical-note",
            json={"content": "not my patient", "is_shared_with_patient": True},
        )
        assert resp.status_code == 404

    def test_clinical_note_encrypted_at_rest(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        booking = _create_draft(patient_client, verified_doctor, clinic_location)

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        secret_text = "patient has a rare allergy to penicillin"
        doctor_client.put(
            f"/api/v1/bookings/{booking['id']}/clinical-note",
            json={"content": secret_text, "is_shared_with_patient": False},
        )

        raw = session.exec(
            text("SELECT content FROM clinical_notes WHERE booking_id = CAST(:bid AS uuid)").bindparams(
                bid=booking["id"]
            )
        ).one()
        assert secret_text not in raw[0]
