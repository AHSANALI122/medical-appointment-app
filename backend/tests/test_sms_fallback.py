from app.models.enums import NotificationPreference
from app.models.notification import Notification, NotificationChannel, NotificationStatus
from app.services import notification_service
from sqlmodel import select


def _login_patient(client, patient_user):
    resp = client.post("/api/v1/auth/login", json={"email": patient_user.email, "password": "password123"})
    assert resp.status_code == 200


def _login_doctor(client, email="doctor@example.com"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200


def _set_phone(session, user, phone="+923001234567"):
    user.phone = phone
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class TestChannelPriority:
    def test_default_preference_sends_in_app_and_email_only(self, session, patient_user):
        _set_phone(session, patient_user)
        notification_service.notify_user(
            session, user_id=patient_user.id, booking=None, title="Booking confirmed", body="see you then"
        )
        channels = {
            n.channel
            for n in session.exec(select(Notification).where(Notification.user_id == patient_user.id)).all()
        }
        assert channels == {NotificationChannel.IN_APP, NotificationChannel.EMAIL}

    def test_sms_first_preference_sends_sms_immediately(self, session, patient_user):
        _set_phone(session, patient_user)
        patient_user.notification_preference = NotificationPreference.SMS_FIRST
        session.add(patient_user)
        session.commit()

        notification_service.notify_user(
            session, user_id=patient_user.id, booking=None, title="Appointment reminder", body="in 1 hour"
        )
        sms = session.exec(
            select(Notification).where(
                Notification.user_id == patient_user.id, Notification.channel == NotificationChannel.SMS
            )
        ).first()
        assert sms is not None
        assert sms.status == NotificationStatus.SENT
        # bilingual template: English body plus Urdu title in parentheses
        assert "in 1 hour" in sms.body
        assert "یاد دہانی" in sms.body

    def test_sms_first_without_phone_on_file_does_not_crash(self, session, patient_user):
        patient_user.notification_preference = NotificationPreference.SMS_FIRST
        session.add(patient_user)
        session.commit()

        notification_service.notify_user(
            session, user_id=patient_user.id, booking=None, title="Booking confirmed", body="see you then"
        )
        sms = session.exec(
            select(Notification).where(
                Notification.user_id == patient_user.id, Notification.channel == NotificationChannel.SMS
            )
        ).first()
        assert sms is None


class TestEmailBounceTriggersSMS:
    def test_bounce_webhook_sends_sms_fallback(self, client, session, patient_user):
        _set_phone(session, patient_user)
        notification_service.notify_user(
            session, user_id=patient_user.id, booking=None, title="Booking confirmed", body="Rs. 1500 at City Clinic"
        )
        email = session.exec(
            select(Notification).where(
                Notification.user_id == patient_user.id, Notification.channel == NotificationChannel.EMAIL
            )
        ).first()
        assert email is not None
        assert email.provider_message_id is not None

        resp = client.post(
            "/api/v1/notifications/webhooks/email-bounce",
            json={"provider_message_id": email.provider_message_id, "reason": "hard_bounce"},
        )
        assert resp.status_code == 200
        sms_payload = resp.json()
        assert sms_payload is not None
        assert sms_payload["channel"] == "sms"

        session.refresh(email)
        assert email.status == NotificationStatus.FAILED
        assert email.failure_reason == "hard_bounce"

        sms = session.exec(
            select(Notification).where(
                Notification.user_id == patient_user.id, Notification.channel == NotificationChannel.SMS
            )
        ).first()
        assert sms is not None

    def test_bounce_webhook_unknown_id_is_a_noop(self, client):
        resp = client.post(
            "/api/v1/notifications/webhooks/email-bounce",
            json={"provider_message_id": "does-not-exist", "reason": "hard_bounce"},
        )
        assert resp.status_code == 200
        assert resp.json() is None

    def test_bounce_webhook_secret_enforced_when_configured(self, client, monkeypatch):
        from app.api.v1 import notifications as notifications_router

        class _FakeSettings:
            resend_webhook_secret = "topsecret"

        monkeypatch.setattr(notifications_router, "get_settings", lambda: _FakeSettings())

        resp = client.post(
            "/api/v1/notifications/webhooks/email-bounce",
            json={"provider_message_id": "whatever", "reason": "hard_bounce"},
        )
        assert resp.status_code == 401

        resp_ok = client.post(
            "/api/v1/notifications/webhooks/email-bounce",
            json={"provider_message_id": "whatever", "reason": "hard_bounce"},
            headers={"X-Webhook-Secret": "topsecret"},
        )
        assert resp_ok.status_code == 200


class TestDeliveryReport:
    def test_patient_can_view_own_booking_delivery_report(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        from datetime import timedelta

        from app.core.timezone import now_utc

        _set_phone(session, patient_user)
        patient_client = client_factory()
        _login_patient(patient_client, patient_user)

        start = now_utc() + timedelta(minutes=60)
        end = start + timedelta(minutes=30)
        booking = patient_client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": start.isoformat(),
                "end_time_utc": end.isoformat(),
            },
        ).json()
        patient_client.post(f"/api/v1/bookings/{booking['id']}/confirm")

        doctor_client = client_factory()
        _login_doctor(doctor_client)
        doctor_client.post(f"/api/v1/bookings/{booking['id']}/accept")

        report_resp = patient_client.get(f"/api/v1/notifications/booking/{booking['id']}/delivery-report")
        assert report_resp.status_code == 200
        channels = {row["channel"] for row in report_resp.json()}
        assert "in_app" in channels
        assert "email" in channels

        doctor_view = doctor_client.get(f"/api/v1/notifications/booking/{booking['id']}/delivery-report")
        assert doctor_view.status_code == 200

    def test_unrelated_patient_cannot_view_delivery_report(
        self, client_factory, session, patient_user, verified_doctor, clinic_location
    ):
        from datetime import timedelta

        from app.core.timezone import now_utc

        patient_client = client_factory()
        _login_patient(patient_client, patient_user)
        start = now_utc() + timedelta(minutes=60)
        end = start + timedelta(minutes=30)
        booking = patient_client.post(
            "/api/v1/bookings",
            json={
                "doctor_id": str(verified_doctor.id),
                "clinic_location_id": str(clinic_location.id),
                "start_time_utc": start.isoformat(),
                "end_time_utc": end.isoformat(),
            },
        ).json()

        intruder = client_factory()
        intruder.post(
            "/api/v1/auth/register/patient",
            json={"email": "sms-intruder@example.com", "password": "password123", "full_name": "Intruder"},
        )
        resp = intruder.get(f"/api/v1/notifications/booking/{booking['id']}/delivery-report")
        assert resp.status_code == 403
