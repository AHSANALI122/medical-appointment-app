from datetime import timedelta

from app.core.timezone import now_utc


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def _login_doctor(client, email="doctor@example.com"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200


def _create_and_confirm(client, client_factory, verified_doctor, clinic_location, minutes_ahead=60):
    """Drives a booking all the way to `confirmed` — the patient notification
    (which the notification-center tests need) is only sent on doctor accept,
    not on the patient's draft->pending tap."""
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
    booking = resp.json()
    client.post(f"/api/v1/bookings/{booking['id']}/confirm")

    doctor_client = client_factory()
    _login_doctor(doctor_client)
    accept_resp = doctor_client.post(f"/api/v1/bookings/{booking['id']}/accept")
    assert accept_resp.status_code == 200
    return booking


class TestNotificationCenter:
    def test_unread_count_and_list(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location)

        count_resp = patient_client.get("/api/v1/notifications/unread-count")
        assert count_resp.status_code == 200
        assert count_resp.json()["unread_count"] >= 1

        list_resp = patient_client.get("/api/v1/notifications")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1

    def test_mark_single_read_decrements_count(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location)

        before = patient_client.get("/api/v1/notifications/unread-count").json()["unread_count"]
        notif_id = patient_client.get("/api/v1/notifications").json()["items"][0]["id"]

        read_resp = patient_client.post(f"/api/v1/notifications/{notif_id}/read")
        assert read_resp.status_code == 200
        assert read_resp.json()["read_at"] is not None

        after = patient_client.get("/api/v1/notifications/unread-count").json()["unread_count"]
        assert after == before - 1

    def test_mark_all_read(self, client_factory, session, patient_user, verified_doctor, clinic_location):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location, minutes_ahead=60)
        _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location, minutes_ahead=120)

        resp = patient_client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        assert resp.json()["unread_count"] == 0

        after = patient_client.get("/api/v1/notifications/unread-count")
        assert after.json()["unread_count"] == 0

    def test_cannot_read_another_users_notification(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        _create_and_confirm(patient_client, client_factory, verified_doctor, clinic_location)
        notif_id = patient_client.get("/api/v1/notifications").json()["items"][0]["id"]

        intruder_client = client_factory()
        intruder_client.post(
            "/api/v1/auth/register/patient",
            json={
                "email": "notif-intruder@example.com",
                "password": "password123",
                "full_name": "Intruder",
            },
        )
        resp = intruder_client.post(f"/api/v1/notifications/{notif_id}/read")
        assert resp.status_code == 404
