"""F20 — family accounts: additional PatientProfile records under one User,
booking on behalf of a dependent, and the IDOR check that a profile_id
belonging to a different user is always rejected."""

from app.core.exceptions import PolicyViolationError
from app.core.timezone import now_utc
from app.services import feature_flag_service, patient_profile_service
from tests.conftest import make_patient


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


class TestPatientProfileService:
    def test_create_dependent_profile(self, session, patient_user):
        profile = patient_profile_service.create_dependent_profile(
            session, user_id=patient_user.id, full_name="Ammi", relationship_label="mother", date_of_birth=None
        )
        assert profile.relationship_label == "mother"
        assert profile.user_id == patient_user.id

    def test_cannot_create_dependent_profile_named_self(self, session, patient_user):
        try:
            patient_profile_service.create_dependent_profile(
                session, user_id=patient_user.id, full_name="X", relationship_label="self", date_of_birth=None
            )
            raise AssertionError("expected PolicyViolationError")
        except PolicyViolationError:
            pass

    def test_list_includes_self_and_dependents(self, session, patient_user):
        patient_profile_service.create_dependent_profile(
            session, user_id=patient_user.id, full_name="Ammi", relationship_label="mother", date_of_birth=None
        )
        profiles = patient_profile_service.list_profiles_for_user(session, user_id=patient_user.id)
        labels = {p.relationship_label for p in profiles}
        assert labels == {"self", "mother"}


class TestPatientProfileRouter:
    def test_add_and_list_dependent_profile_via_api(self, client, patient_user):
        _login_patient(client, patient_user)
        create_resp = client.post(
            "/api/v1/patient-profiles", json={"full_name": "Abba", "relationship_label": "father"}
        )
        assert create_resp.status_code == 201
        profile_id = create_resp.json()["id"]

        list_resp = client.get("/api/v1/patient-profiles")
        assert list_resp.status_code == 200
        assert any(p["id"] == profile_id for p in list_resp.json())

    def test_disabled_feature_flag_blocks_route(self, client, session, patient_user):
        feature_flag_service.set_enabled(session, key=feature_flag_service.FAMILY_ACCOUNTS, enabled=False)
        _login_patient(client, patient_user)
        resp = client.post("/api/v1/patient-profiles", json={"full_name": "Abba", "relationship_label": "father"})
        assert resp.status_code == 403


class TestBookOnBehalfOfDependent:
    def test_booking_with_own_dependent_profile_succeeds(
        self, client, session, patient_user, verified_doctor, clinic_location
    ):
        _login_patient(client, patient_user)
        dependent_resp = client.post(
            "/api/v1/patient-profiles", json={"full_name": "Ammi", "relationship_label": "mother"}
        )
        dependent_id = dependent_resp.json()["id"]

        start = now_utc().replace(microsecond=0)
        from datetime import timedelta

        start = start + timedelta(minutes=90)
        end = start + timedelta(minutes=30)

        draft_resp = client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": start.isoformat(),
                "end_time_utc": end.isoformat(),
                "patient_profile_id": dependent_id,
            },
        )
        assert draft_resp.status_code == 201
        assert draft_resp.json()["patient_profile_id"] == dependent_id

    def test_booking_with_foreign_profile_id_is_rejected(
        self, client, session, patient_user, verified_doctor, clinic_location
    ):
        foreign_profile = make_patient(session, "family-foreign@example.com")
        _login_patient(client, patient_user)

        from datetime import timedelta

        start = now_utc() + timedelta(minutes=90)
        end = start + timedelta(minutes=30)

        resp = client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": start.isoformat(),
                "end_time_utc": end.isoformat(),
                "patient_profile_id": str(foreign_profile.id),
            },
        )
        assert resp.status_code == 403
