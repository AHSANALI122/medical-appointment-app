"""F27 acceptance: "export endpoint returns complete data"."""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.core.timezone import now_utc
from app.models.audit_log import AuditLog
from app.models.enums import ReviewModerationStatus
from app.models.medical_history import MedicalHistory
from app.models.note import ClinicalNote, PatientNote
from app.models.review import Review
from app.services import data_export_service
from app.services.state_machine import BookingStateMachine


@pytest.fixture
def completed_booking(session, patient_profile, verified_doctor, clinic_location):
    machine = BookingStateMachine(session)
    start = now_utc() + timedelta(hours=2)
    booking = machine.create_draft(
        patient_profile_id=patient_profile.id,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        start_time_utc=start,
        end_time_utc=start + timedelta(minutes=30),
        fee_charged=2500,
        address_snapshot="123 Main Blvd, Lahore",
    )
    machine.confirm(booking)
    machine.doctor_accept(booking)
    booking.start_time_utc = now_utc() - timedelta(hours=1)
    machine.mark_completed(booking)
    return booking


class TestBuildExport:
    def test_includes_account_and_profiles(self, session, patient_user, patient_profile):
        export = data_export_service.build_export(session, user=patient_user)

        assert export["account"]["email"] == patient_user.email
        assert export["account"]["id"] == str(patient_user.id)
        assert [p["id"] for p in export["patient_profiles"]] == [str(patient_profile.id)]

    def test_includes_bookings_with_own_notes(
        self, session, patient_user, patient_profile, completed_booking
    ):
        session.add(
            PatientNote(
                booking_id=completed_booking.id,
                patient_profile_id=patient_profile.id,
                content="sar mein dard tha",
            )
        )
        session.commit()

        export = data_export_service.build_export(session, user=patient_user)

        (booking,) = export["bookings"]
        assert booking["id"] == str(completed_booking.id)
        assert booking["fee_charged"] == 2500
        assert booking["my_note"] == "sar mein dard tha"

    def test_shared_clinical_note_is_included(
        self, session, patient_user, verified_doctor, completed_booking
    ):
        session.add(
            ClinicalNote(
                booking_id=completed_booking.id,
                doctor_id=verified_doctor.id,
                content="Prescribed rest and fluids.",
                is_shared_with_patient=True,
            )
        )
        session.commit()

        export = data_export_service.build_export(session, user=patient_user)

        assert export["bookings"][0]["doctor_note_shared_with_me"] == "Prescribed rest and fluids."

    def test_private_clinical_note_is_not_leaked_by_the_export(
        self, session, patient_user, verified_doctor, completed_booking
    ):
        """The export must not become a backdoor around the doctor's
        private-by-default notes (F6)."""
        session.add(
            ClinicalNote(
                booking_id=completed_booking.id,
                doctor_id=verified_doctor.id,
                content="Suspect malingering; do not share.",
                is_shared_with_patient=False,
            )
        )
        session.commit()

        export = data_export_service.build_export(session, user=patient_user)

        assert export["bookings"][0]["doctor_note_shared_with_me"] is None
        assert "malingering" not in str(export)

    def test_medical_history_includes_every_version(self, session, patient_user, patient_profile):
        for version, allergies in ((1, "penicillin"), (2, "penicillin, sulfa")):
            session.add(
                MedicalHistory(
                    patient_profile_id=patient_profile.id,
                    version=version,
                    allergies=allergies,
                    edited_by_user_id=patient_user.id,
                )
            )
        session.commit()

        export = data_export_service.build_export(session, user=patient_user)

        assert [h["version"] for h in export["medical_history"]] == [1, 2]
        assert export["medical_history"][1]["allergies"] == "penicillin, sulfa"

    def test_includes_reviews(
        self, session, patient_user, patient_profile, verified_doctor, completed_booking
    ):
        session.add(
            Review(
                booking_id=completed_booking.id,
                patient_profile_id=patient_profile.id,
                doctor_id=verified_doctor.id,
                rating=5,
                comment="Very helpful",
                moderation_status=ReviewModerationStatus.APPROVED,
            )
        )
        session.commit()

        export = data_export_service.build_export(session, user=patient_user)

        assert export["reviews"][0]["rating"] == 5
        assert export["reviews"][0]["comment"] == "Very helpful"

    def test_export_is_audit_logged(self, session, patient_user, patient_profile):
        data_export_service.build_export(session, user=patient_user)

        logs = session.exec(select(AuditLog).where(AuditLog.action == "data_export")).all()
        assert len(logs) == 1
        assert logs[0].actor_user_id == patient_user.id
        assert logs[0].resource_id == patient_profile.id

    def test_empty_account_exports_cleanly(self, session, patient_user):
        export = data_export_service.build_export(session, user=patient_user)

        assert export["bookings"] == []
        assert export["medical_history"] == []
        assert export["reviews"] == []


class TestExportEndpoint:
    def test_requires_authentication(self, client_factory):
        assert client_factory().get("/api/v1/account/export").status_code == 401

    def test_returns_a_json_download(self, client_factory, patient_user):
        client = client_factory()
        client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})

        response = client.get("/api/v1/account/export")

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert response.json()["account"]["email"] == patient_user.email

    def test_only_ever_exports_the_caller(self, client_factory, session, patient_user):
        """There is no user_id parameter to tamper with — identity comes
        from the JWT (CLAUDE.md rule 8). This pins that shape."""
        from tests.conftest import make_patient

        other = make_patient(session, "someone-else@example.com")
        client = client_factory()
        client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})

        export = client.get("/api/v1/account/export").json()

        exported_profile_ids = {p["id"] for p in export["patient_profiles"]}
        assert str(other.id) not in exported_profile_ids
