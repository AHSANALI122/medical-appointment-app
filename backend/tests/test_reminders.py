from datetime import timedelta

from app.core.timezone import now_utc
from app.jobs.reminders import send_due_reminders
from app.models.notification import Notification, NotificationChannel
from app.models.reminder import ReminderLog, ReminderOffset
from app.services.state_machine import BookingStateMachine
from sqlmodel import select


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


class TestReminderSweep:
    def test_sends_24h_reminder_when_due(self, session, patient_profile, verified_doctor, clinic_location):
        # "Due" means time-until-start has already crossed below 24h — the
        # CATCH_UP_WINDOW is a look-back, not a look-ahead (see reminders.py).
        booking = _confirmed_booking(
            session, patient_profile, verified_doctor, clinic_location, start_in=timedelta(hours=23, minutes=58)
        )
        sent = send_due_reminders(session)
        assert sent == 1

        log = session.exec(
            select(ReminderLog).where(
                ReminderLog.booking_id == booking.id, ReminderLog.offset == ReminderOffset.T_24H
            )
        ).first()
        assert log is not None

        notif = session.exec(
            select(Notification).where(
                Notification.booking_id == booking.id, Notification.channel == NotificationChannel.IN_APP
            )
        ).first()
        assert notif is not None
        assert "24 hours" in notif.body

    def test_sends_1h_reminder_when_due(self, session, patient_profile, verified_doctor, clinic_location):
        booking = _confirmed_booking(
            session, patient_profile, verified_doctor, clinic_location, start_in=timedelta(minutes=55)
        )
        sent = send_due_reminders(session)
        assert sent == 1

        log = session.exec(
            select(ReminderLog).where(
                ReminderLog.booking_id == booking.id, ReminderLog.offset == ReminderOffset.T_1H
            )
        ).first()
        assert log is not None

    def test_not_yet_due_reminder_is_skipped(self, session, patient_profile, verified_doctor, clinic_location):
        _confirmed_booking(
            session, patient_profile, verified_doctor, clinic_location, start_in=timedelta(hours=48)
        )
        sent = send_due_reminders(session)
        assert sent == 0

    def test_sweep_is_idempotent(self, session, patient_profile, verified_doctor, clinic_location):
        _confirmed_booking(
            session, patient_profile, verified_doctor, clinic_location, start_in=timedelta(hours=23, minutes=58)
        )
        first = send_due_reminders(session)
        second = send_due_reminders(session)
        assert first == 1
        assert second == 0

    def test_cancelled_booking_never_gets_reminder(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        """F12 acceptance: reschedule/cancel means stale reminders never fire."""
        booking = _confirmed_booking(
            session, patient_profile, verified_doctor, clinic_location, start_in=timedelta(hours=23, minutes=58)
        )
        machine = BookingStateMachine(session)
        machine.cancel(
            booking, cancelled_by="patient", reason="can't make it", cancellation_policy_hours=2
        )

        sent = send_due_reminders(session)
        assert sent == 0

        log = session.exec(select(ReminderLog).where(ReminderLog.booking_id == booking.id)).first()
        assert log is None

    def test_only_confirmed_bookings_get_reminders(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        pending_booking = machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=now_utc() + timedelta(hours=23, minutes=58),
            end_time_utc=now_utc() + timedelta(hours=24, minutes=31),
            fee_charged=verified_doctor.consultation_fee,
            address_snapshot="Test Clinic",
        )
        machine.confirm(pending_booking)  # stays `pending`, never accepted

        sent = send_due_reminders(session)
        assert sent == 0
