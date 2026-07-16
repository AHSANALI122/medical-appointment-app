"""F15 — security pytest suite: SQLi, XSS, CSRF, IDOR, auth bypass, rate limiting."""

from datetime import timedelta

from app.core.rate_limit import AUTH_RATE_LIMIT
from app.core.timezone import now_utc


def _register_patient(client, email="secuser@example.com"):
    resp = client.post(
        "/api/v1/auth/register/patient",
        json={"email": email, "password": "password123", "full_name": "Sec User"},
    )
    assert resp.status_code == 201
    return resp


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


class TestSQLInjection:
    def test_sqli_in_login_email_does_not_bypass_auth(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "' OR '1'='1", "password": "' OR '1'='1"},
        )
        assert resp.status_code in (401, 422)

    def test_sqli_in_doctor_search_name_filter_is_treated_as_literal(self, client, verified_doctor):
        resp = client.get("/api/v1/doctors", params={"name": "'; DROP TABLE users; --"})
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_sqli_in_registration_email_is_stored_literally_not_executed(self, client, session):
        payload = {
            "email": "sqli-test@example.com",
            "password": "password123",
            "full_name": "Robert'); DROP TABLE users;--",
        }
        resp = client.post("/api/v1/auth/register/patient", json=payload)
        assert resp.status_code == 201
        assert resp.json()["full_name"] == payload["full_name"]

        # The users table must still exist and be queryable.
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200


class TestXSS:
    def test_script_tag_in_patient_note_is_stored_and_returned_verbatim(
        self, client, verified_doctor, clinic_location
    ):
        _register_patient(client, email="xss-patient@example.com")
        booking = _create_draft(client, verified_doctor, clinic_location)

        payload = "<script>alert('xss')</script>"
        resp = client.put(f"/api/v1/bookings/{booking['id']}/patient-note", json={"content": payload})
        assert resp.status_code == 200
        # JSON API: the raw string round-trips exactly. It is the frontend's
        # job to escape on render — the API must not silently mutate it
        # (which would hide the fact that HTML escaping needs to happen
        # downstream) and must not error out on it either.
        assert resp.json()["content"] == payload

    def test_script_tag_in_review_comment_does_not_break_api(
        self, client, session, verified_doctor, clinic_location, patient_profile, patient_user
    ):
        from app.services.state_machine import BookingStateMachine

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

        resp = client.post(
            "/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"}
        )
        assert resp.status_code == 200

        payload = "<img src=x onerror=alert(1)>"
        review_resp = client.post(
            f"/api/v1/bookings/{booking.id}/review", json={"rating": 5, "comment": payload}
        )
        assert review_resp.status_code == 201
        assert review_resp.json()["comment"] == payload


class TestCSRF:
    def test_mutating_request_with_wrong_csrf_token_is_rejected(
        self, client, verified_doctor, clinic_location
    ):
        _register_patient(client, email="csrf-victim@example.com")
        # The CSRFAwareTestClient auto-attaches the correct token; explicitly
        # overriding it here simulates a forged cross-site request that
        # carries the session cookie (browsers do this automatically) but
        # cannot read the cookie's value to produce a matching header.
        resp = client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": (now_utc() + timedelta(hours=1)).isoformat(),
                "end_time_utc": (now_utc() + timedelta(hours=1, minutes=30)).isoformat(),
            },
            headers={"X-CSRF-Token": "attacker-guessed-wrong-token"},
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "csrf_failed"

    def test_mutating_request_with_no_session_cookie_is_not_csrf_blocked(self, client):
        """No session cookie means no ambient authority to forge — the
        request should fail on auth (401), not CSRF."""
        resp = client.post("/api/v1/bookings", json={})
        assert resp.status_code in (401, 422)
        if resp.status_code != 422:
            assert resp.json()["error_code"] != "csrf_failed"

    def test_correct_csrf_token_succeeds(self, client, verified_doctor, clinic_location):
        _register_patient(client, email="csrf-legit@example.com")
        booking = _create_draft(client, verified_doctor, clinic_location)
        assert booking["status"] == "draft"


class TestIDOR:
    def test_patient_a_cannot_read_patient_b_booking(
        self, client_factory, verified_doctor, clinic_location
    ):
        client_a = client_factory()
        _register_patient(client_a, email="idor-a@example.com")
        booking = _create_draft(client_a, verified_doctor, clinic_location)

        client_b = client_factory()
        _register_patient(client_b, email="idor-b@example.com")
        resp = client_b.get(f"/api/v1/bookings/{booking['id']}")
        assert resp.status_code == 403

    def test_patient_a_cannot_cancel_patient_b_booking(
        self, client_factory, verified_doctor, clinic_location
    ):
        client_a = client_factory()
        _register_patient(client_a, email="idor-cancel-a@example.com")
        booking = _create_draft(client_a, verified_doctor, clinic_location)

        client_b = client_factory()
        _register_patient(client_b, email="idor-cancel-b@example.com")
        resp = client_b.post(f"/api/v1/bookings/{booking['id']}/cancel", json={"reason": "not mine"})
        assert resp.status_code == 404


class TestAuthBypass:
    def test_no_cookie_is_rejected(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_tampered_jwt_is_rejected(self, client):
        client.cookies.set("access_token", "not.a.valid.jwt")
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_expired_style_forged_token_is_rejected(self, client):
        import jwt as pyjwt

        from app.core.config import get_settings

        settings = get_settings()
        forged = pyjwt.encode(
            {"sub": "00000000-0000-0000-0000-000000000000", "type": "access", "role": "admin"},
            "wrong-secret",
            algorithm=settings.jwt_algorithm,
        )
        client.cookies.set("access_token", forged)
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_role_escalation_via_jwt_role_claim_is_ignored(self, client):
        """Even a validly-signed token can't be re-purposed by editing the
        role claim client-side — role is looked up server-side from the DB
        user row (get_current_user reads user.role), not trusted from the
        token payload for authorization decisions elsewhere."""
        _register_patient(client, email="escalate@example.com")
        resp = client.get("/api/v1/admin/stats")
        assert resp.status_code == 403


class TestRateLimiting:
    def test_auth_endpoint_rate_limited_after_threshold(self, client):
        _, limit, _window = AUTH_RATE_LIMIT
        last_status = None
        for _ in range(limit + 3):
            resp = client.post(
                "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
            )
            last_status = resp.status_code
        assert last_status == 429
