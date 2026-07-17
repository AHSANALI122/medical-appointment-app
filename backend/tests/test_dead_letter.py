from datetime import timedelta

from sqlmodel import select

from app.core.timezone import now_utc
from app.jobs.reminders import send_due_reminders
from app.models.dead_letter import DeadLetterJob
from app.services import notification_service
from app.services.state_machine import BookingStateMachine


def _confirmed_booking(session, patient_profile, verified_doctor, clinic_location, *, start_in: timedelta):
    machine = BookingStateMachine(session)
    booking = machine.create_draft(
        patient_profile_id=patient_profile.id,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        start_time_utc=now_utc() + start_in,
        end_time_utc=now_utc() + start_in + timedelta(minutes=30),
        fee_charged=verified_doctor.consultation_fee,
        address_snapshot="Test Clinic",
    )
    booking = machine.confirm(booking)
    booking = machine.doctor_accept(booking)
    return booking


class TestReminderDeadLetter:
    def test_notifier_failure_is_dead_lettered_not_crashed(
        self, session, patient_profile, verified_doctor, clinic_location, monkeypatch
    ):
        booking = _confirmed_booking(
            session, patient_profile, verified_doctor, clinic_location, start_in=timedelta(hours=23, minutes=58)
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("email provider unreachable")

        monkeypatch.setattr(notification_service, "notify_user", _boom)

        sent = send_due_reminders(session)
        assert sent == 0

        entries = session.exec(
            select(DeadLetterJob).where(DeadLetterJob.reference_id == booking.id)
        ).all()
        assert len(entries) == 1
        assert entries[0].job_type == "reminder"
        assert "email provider unreachable" in entries[0].error
        assert entries[0].alerted_at is None

    def test_repeat_failures_trigger_alert(
        self, session, patient_profile, verified_doctor, clinic_location, monkeypatch
    ):
        def _boom(*args, **kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(notification_service, "notify_user", _boom)

        for i in range(3):
            _confirmed_booking(
                session,
                patient_profile,
                verified_doctor,
                clinic_location,
                start_in=timedelta(hours=23, minutes=58, seconds=i),
            )
        send_due_reminders(session)

        entries = session.exec(select(DeadLetterJob).where(DeadLetterJob.job_type == "reminder")).all()
        assert len(entries) == 3
        assert all(e.alerted_at is not None for e in entries)
