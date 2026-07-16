from datetime import timedelta

import pytest
from sqlmodel import Session

from app.core.exceptions import BookingConflictError, PolicyViolationError, SlotUnavailableError
from app.core.timezone import now_utc
from app.models.doctor import ClinicLocation, DoctorProfile
from app.models.enums import BookingStatus, CancelledBy, DoctorVerificationStatus, UserRole
from app.models.user import PatientProfile, User
from app.services.state_machine import BookingStateMachine, IllegalTransitionError
from tests.conftest import make_patient


def _draft(
    session: Session,
    patient_profile: PatientProfile,
    verified_doctor: DoctorProfile,
    clinic_location: ClinicLocation,
    minutes_ahead: int = 60,
):
    machine = BookingStateMachine(session)
    start = now_utc() + timedelta(minutes=minutes_ahead)
    return machine.create_draft(
        patient_profile_id=patient_profile.id,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        start_time_utc=start,
        end_time_utc=start + timedelta(minutes=30),
        fee_charged=verified_doctor.consultation_fee,
        address_snapshot="123 Main Blvd, Lahore",
    )


class TestLegalTransitions:
    def test_draft_to_pending(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = _draft(session, patient_profile, verified_doctor, clinic_location)
        assert booking.status == BookingStatus.DRAFT

        pending = machine.confirm(booking)
        assert pending.status == BookingStatus.PENDING
        assert pending.expires_at is not None

    def test_pending_to_confirmed(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        confirmed = machine.doctor_accept(booking)
        assert confirmed.status == BookingStatus.CONFIRMED
        assert confirmed.confirmed_at is not None
        assert confirmed.expires_at is None

    def test_pending_to_rejected(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        rejected = machine.doctor_reject(booking, reason="fully booked")
        assert rejected.status == BookingStatus.REJECTED
        assert rejected.rejected_reason == "fully booked"

    def test_draft_to_expired(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = _draft(session, patient_profile, verified_doctor, clinic_location)
        expired = machine.expire(booking)
        assert expired.status == BookingStatus.EXPIRED

    def test_pending_to_expired(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        expired = machine.expire(booking)
        assert expired.status == BookingStatus.EXPIRED

    def test_pending_to_cancelled_by_patient(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = machine.confirm(
            _draft(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=60 * 5)
        )
        cancelled = machine.cancel(
            booking, cancelled_by=CancelledBy.PATIENT, reason="changed my mind", cancellation_policy_hours=2
        )
        assert cancelled.status == BookingStatus.CANCELLED

    def test_confirmed_to_cancelled_by_doctor_anytime(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.confirm(
            _draft(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=90)
        )
        booking = machine.doctor_accept(booking)
        cancelled = machine.cancel(
            booking, cancelled_by=CancelledBy.DOCTOR, reason="emergency", cancellation_policy_hours=2
        )
        assert cancelled.status == BookingStatus.CANCELLED
        assert cancelled.cancelled_by == CancelledBy.DOCTOR

    def test_confirmed_to_completed(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = machine.doctor_accept(
            machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        )
        completed = machine.mark_completed(booking)
        assert completed.status == BookingStatus.COMPLETED

    def test_completed_to_no_show_correction_window(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.mark_completed(
            machine.doctor_accept(
                machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
            )
        )
        corrected = machine.correct_completion(booking, target=BookingStatus.NO_SHOW)
        assert corrected.status == BookingStatus.NO_SHOW

    def test_no_show_to_completed_correction_window(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.doctor_accept(
            machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        )
        booking.start_time_utc = now_utc() - timedelta(minutes=5)
        session.add(booking)
        session.commit()
        no_show = machine.mark_no_show(booking)
        corrected = machine.correct_completion(no_show, target=BookingStatus.COMPLETED)
        assert corrected.status == BookingStatus.COMPLETED


class TestIllegalTransitions:
    def test_cannot_accept_a_draft(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = _draft(session, patient_profile, verified_doctor, clinic_location)
        with pytest.raises(IllegalTransitionError):
            machine.doctor_accept(booking)

    def test_cannot_reject_a_confirmed_booking(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.doctor_accept(
            machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        )
        with pytest.raises(IllegalTransitionError):
            machine.doctor_reject(booking, reason="too late")

    def test_cannot_transition_out_of_cancelled(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        pending = machine.confirm(
            _draft(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=60 * 5)
        )
        booking = machine.cancel(
            pending,
            cancelled_by=CancelledBy.PATIENT,
            reason="nvm",
            cancellation_policy_hours=2,
        )
        with pytest.raises(IllegalTransitionError):
            machine.doctor_accept(booking)

    def test_cannot_cancel_a_draft_directly(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        booking = _draft(session, patient_profile, verified_doctor, clinic_location)
        with pytest.raises(IllegalTransitionError):
            machine.cancel(
                booking, cancelled_by=CancelledBy.PATIENT, reason="nvm", cancellation_policy_hours=2
            )

    def test_cannot_transition_out_of_rejected(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.doctor_reject(
            machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location)),
            reason="no",
        )
        with pytest.raises(IllegalTransitionError):
            machine.confirm(booking)

    def test_cannot_transition_out_of_expired(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.expire(_draft(session, patient_profile, verified_doctor, clinic_location))
        with pytest.raises(IllegalTransitionError):
            machine.confirm(booking)

    def test_expired_draft_cannot_be_confirmed_even_before_sweep(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = _draft(session, patient_profile, verified_doctor, clinic_location)
        booking.expires_at = now_utc() - timedelta(seconds=1)
        session.add(booking)
        session.commit()
        with pytest.raises(PolicyViolationError):
            machine.confirm(booking)

    def test_patient_cancel_blocked_within_policy_window(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.doctor_accept(
            machine.confirm(
                _draft(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=90)
            )
        )
        with pytest.raises(PolicyViolationError):
            machine.cancel(
                booking, cancelled_by=CancelledBy.PATIENT, reason="late", cancellation_policy_hours=2
            )

    def test_patient_cancel_allowed_outside_policy_window(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.doctor_accept(
            machine.confirm(
                _draft(session, patient_profile, verified_doctor, clinic_location, minutes_ahead=60 * 5)
            )
        )
        cancelled = machine.cancel(
            booking, cancelled_by=CancelledBy.PATIENT, reason="ok", cancellation_policy_hours=2
        )
        assert cancelled.status == BookingStatus.CANCELLED

    def test_cannot_mark_no_show_before_start_time(
        self, session, patient_profile, verified_doctor, clinic_location
    ):
        machine = BookingStateMachine(session)
        booking = machine.doctor_accept(
            machine.confirm(_draft(session, patient_profile, verified_doctor, clinic_location))
        )
        with pytest.raises(PolicyViolationError):
            machine.mark_no_show(booking)


class TestDraftCreationGuards:
    def test_slot_conflict_raises(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        start = now_utc() + timedelta(minutes=60)
        end = start + timedelta(minutes=30)

        machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=start,
            end_time_utc=end,
            fee_charged=1500,
            address_snapshot="addr",
        )

        other_patient = make_patient(session, "other@example.com")
        with pytest.raises(SlotUnavailableError):
            machine.create_draft(
                patient_profile_id=other_patient.id,
                doctor_id=verified_doctor.id,
                clinic_location_id=clinic_location.id,
                start_time_utc=start,
                end_time_utc=end,
                fee_charged=1500,
                address_snapshot="addr",
            )

    def test_create_draft_is_idempotent(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        start = now_utc() + timedelta(minutes=60)
        end = start + timedelta(minutes=30)
        kwargs = dict(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=start,
            end_time_utc=end,
            fee_charged=1500,
            address_snapshot="addr",
        )
        first = machine.create_draft(**kwargs)
        second = machine.create_draft(**kwargs)
        assert first.id == second.id

    def test_max_active_drafts_per_profile(self, session, patient_profile, specialization, clinic_location):
        machine = BookingStateMachine(session)
        doctors = []
        for i in range(4):
            user = User(
                email=f"doc{i}@example.com",
                password_hash="x",
                role=UserRole.DOCTOR,
                full_name=f"Dr. {i}",
            )
            session.add(user)
            session.flush()
            doctor = DoctorProfile(
                user_id=user.id,
                specialization_id=specialization.id,
                pmc_number=f"PMC-{i}",
                consultation_fee=1000,
                verification_status=DoctorVerificationStatus.VERIFIED,
            )
            session.add(doctor)
            session.commit()
            session.refresh(doctor)
            location = ClinicLocation(doctor_id=doctor.id, name="Clinic", address="addr", city="Lahore")
            session.add(location)
            session.commit()
            session.refresh(location)
            doctors.append((doctor, location))

        for i in range(3):
            doctor, location = doctors[i]
            start = now_utc() + timedelta(hours=1 + i)
            machine.create_draft(
                patient_profile_id=patient_profile.id,
                doctor_id=doctor.id,
                clinic_location_id=location.id,
                start_time_utc=start,
                end_time_utc=start + timedelta(minutes=30),
                fee_charged=1500,
                address_snapshot="addr",
            )

        fourth_doctor, fourth_location = doctors[3]
        start = now_utc() + timedelta(hours=10)
        with pytest.raises(BookingConflictError):
            machine.create_draft(
                patient_profile_id=patient_profile.id,
                doctor_id=fourth_doctor.id,
                clinic_location_id=fourth_location.id,
                start_time_utc=start,
                end_time_utc=start + timedelta(minutes=30),
                fee_charged=1500,
                address_snapshot="addr",
            )

    def test_max_one_draft_per_doctor(self, session, patient_profile, verified_doctor, clinic_location):
        machine = BookingStateMachine(session)
        start1 = now_utc() + timedelta(hours=1)
        machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            start_time_utc=start1,
            end_time_utc=start1 + timedelta(minutes=30),
            fee_charged=1500,
            address_snapshot="addr",
        )
        start2 = now_utc() + timedelta(hours=2)
        with pytest.raises(BookingConflictError):
            machine.create_draft(
                patient_profile_id=patient_profile.id,
                doctor_id=verified_doctor.id,
                clinic_location_id=clinic_location.id,
                start_time_utc=start2,
                end_time_utc=start2 + timedelta(minutes=30),
                fee_charged=1500,
                address_snapshot="addr",
            )
