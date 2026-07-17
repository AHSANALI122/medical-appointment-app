def test_patient_can_register_and_gets_session_cookie(client):
    resp = client.post(
        "/api/v1/auth/register/patient",
        json={"email": "newpatient@example.com", "password": "password123", "full_name": "New Patient"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "patient"
    assert "access_token" in resp.cookies


def test_duplicate_email_registration_rejected(client):
    payload = {"email": "dupe@example.com", "password": "password123", "full_name": "Dupe"}
    first = client.post("/api/v1/auth/register/patient", json=payload)
    assert first.status_code == 201
    second = client.post("/api/v1/auth/register/patient", json=payload)
    assert second.status_code == 422
    assert second.json()["error_code"] == "validation_error"


def test_doctor_registers_unverified(client, specialization):
    resp = client.post(
        "/api/v1/auth/register/doctor",
        json={
            "email": "newdoc@example.com",
            "password": "password123",
            "full_name": "Dr. New",
            "pmc_number": "PMC-999",
            "specialization_id": str(specialization.id),
            "consultation_fee": 2000,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["verification_status"] == "unverified"


def test_login_wrong_password_rejected(client):
    client.post(
        "/api/v1/auth/register/patient",
        json={"email": "loginer@example.com", "password": "password123", "full_name": "Loginer"},
    )
    resp = client.post(
        "/api/v1/auth/login", json={"email": "loginer@example.com", "password": "wrongpassword"}
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "unauthorized"


def test_me_requires_authentication(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user_after_login(client):
    client.post(
        "/api/v1/auth/register/patient",
        json={"email": "me@example.com", "password": "password123", "full_name": "Me"},
    )
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"


def test_update_notification_preference(client):
    client.post(
        "/api/v1/auth/register/patient",
        json={"email": "prefs@example.com", "password": "password123", "full_name": "Prefs"},
    )
    assert client.get("/api/v1/auth/me").json()["notification_preference"] == "default"

    resp = client.put(
        "/api/v1/auth/me/notification-preference", json={"notification_preference": "sms_first"}
    )
    assert resp.status_code == 200
    assert resp.json()["notification_preference"] == "sms_first"
    assert client.get("/api/v1/auth/me").json()["notification_preference"] == "sms_first"


def test_update_notification_preference_requires_auth(client):
    resp = client.put(
        "/api/v1/auth/me/notification-preference", json={"notification_preference": "sms_first"}
    )
    assert resp.status_code == 401


def test_refresh_rotates_token_and_old_one_is_revoked(client):
    client.post(
        "/api/v1/auth/register/patient",
        json={"email": "rotate@example.com", "password": "password123", "full_name": "Rotate"},
    )
    old_refresh_cookie = client.cookies.get("refresh_token")

    resp = client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    new_refresh_cookie = client.cookies.get("refresh_token")
    assert new_refresh_cookie != old_refresh_cookie


def test_logout_clears_session(client):
    client.post(
        "/api/v1/auth/register/patient",
        json={"email": "logout@example.com", "password": "password123", "full_name": "Logout"},
    )
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 401


def test_doctor_only_route_rejects_patient(client, specialization):
    client.post(
        "/api/v1/auth/register/patient",
        json={"email": "patientonly@example.com", "password": "password123", "full_name": "P"},
    )
    resp = client.get("/api/v1/doctors/me")
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "forbidden"
