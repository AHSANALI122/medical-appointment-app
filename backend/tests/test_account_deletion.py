"""F27 acceptance: "delete → purge verified by test".

The interesting assertions are the ones about what *survives*: the doctor's
booking history and the review rating. A purge that deletes everything the
patient touched is easy and wrong — it silently rewrites a doctor's public
aggregate rating and puts holes in their appointment history.
"""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.core.exceptions import PolicyViolationError
from app.core.timezone import now_utc
from app.jobs.purge_sweep import sweep_purgeable_accounts
from app.models.agent import AgentMessage, AgentSession
from app.models.audit_log import AuditLog
from app.models.booking import Booking
from app.models.enums import AgentRole, BookingStatus, ReviewModerationStatus
from app.models.medical_history import MedicalHistory
from app.models.note import PatientNote
from app.models.review import Review
from app.models.user import RefreshToken, User
from app.services import account_deletion_service
from app.services.account_deletion_service import ANONYMISED_NAME, PURGE_GRACE_PERIOD
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


class TestRequestDeletion:
    def test_soft_delete_stamps_window_and_deactivates(self, session, patient_user):
        before = now_utc()
        updated = account_deletion_service.request_deletion(session, user=patient_user)

        assert updated.is_active is False
        assert updated.deleted_at is not None
        assert updated.purged_at is None
        # 30-day grace window, per spec.
        assert updated.purge_after >= before + PURGE_GRACE_PERIOD - timedelta(minutes=1)

    def test_revokes_live_refresh_tokens_immediately(self, session, patient_user):
        token = RefreshToken(
            jti="jti-under-test", user_id=patient_user.id, expires_at=now_utc() + timedelta(days=30)
        )
        session.add(token)
        session.commit()

        account_deletion_service.request_deletion(session, user=patient_user)

        session.refresh(token)
        assert token.revoked_at is not None

    def test_is_idempotent_and_does_not_extend_the_window(self, session, patient_user):
        first = account_deletion_service.request_deletion(session, user=patient_user)
        original_deadline = first.purge_after

        second = account_deletion_service.request_deletion(session, user=patient_user)

        assert second.purge_after == original_deadline

    def test_doctor_cannot_self_delete(self, session, verified_doctor):
        doctor_user = session.get(User, verified_doctor.user_id)

        with pytest.raises(PolicyViolationError):
            account_deletion_service.request_deletion(session, user=doctor_user)


class TestCancelDeletion:
    def test_restores_account_inside_the_window(self, session, patient_user):
        account_deletion_service.request_deletion(session, user=patient_user)

        restored = account_deletion_service.cancel_deletion(session, user=patient_user)

        assert restored.is_active is True
        assert restored.deleted_at is None
        assert restored.purge_after is None

    def test_cannot_restore_a_purged_account(self, session, patient_user):
        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        with pytest.raises(PolicyViolationError):
            account_deletion_service.cancel_deletion(session, user=patient_user)


class TestPurge:
    def test_cannot_purge_an_account_that_was_never_deleted(self, session, patient_user):
        with pytest.raises(PolicyViolationError):
            account_deletion_service.purge_account(session, user=patient_user)

    def test_purge_is_idempotent(self, session, patient_user):
        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)
        first_purged_at = patient_user.purged_at

        account_deletion_service.purge_account(session, user=patient_user)  # must not re-scrub

        assert patient_user.purged_at == first_purged_at

    def test_anonymises_the_user_row(self, session, patient_user):
        user_id = patient_user.id
        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        session.refresh(patient_user)
        assert patient_user.full_name == ANONYMISED_NAME
        assert patient_user.phone is None
        assert patient_user.purged_at is not None
        # Email is UNIQUE, so the placeholder must be per-user, and must not
        # be routable.
        assert str(user_id) in patient_user.email
        assert patient_user.email.endswith("@medbook.invalid")

    def test_anonymises_patient_profiles(self, session, patient_user, patient_profile):
        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        session.refresh(patient_profile)
        assert patient_profile.full_name == ANONYMISED_NAME
        assert patient_profile.date_of_birth is None

    def test_hard_deletes_chat_history(self, session, patient_user):
        from app.services import agent_session_service

        agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
        agent_session_service.append_message(
            session, agent_session=agent_session, role=AgentRole.USER, content="pait mein dard hai"
        )

        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        assert session.exec(select(AgentSession).where(AgentSession.user_id == patient_user.id)).all() == []
        assert session.exec(select(AgentMessage)).all() == []

    def test_hard_deletes_medical_history_and_notes(
        self, session, patient_user, patient_profile, completed_booking
    ):
        session.add(
            MedicalHistory(
                patient_profile_id=patient_profile.id,
                version=1,
                allergies="penicillin",
                edited_by_user_id=patient_user.id,
            )
        )
        session.add(
            PatientNote(
                booking_id=completed_booking.id,
                patient_profile_id=patient_profile.id,
                content="sar mein dard",
            )
        )
        session.commit()

        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        assert session.exec(select(MedicalHistory)).all() == []
        assert session.exec(select(PatientNote)).all() == []

    def test_booking_survives_so_doctor_history_stays_intact(
        self, session, patient_user, completed_booking
    ):
        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        survived = session.get(Booking, completed_booking.id)
        assert survived is not None
        assert survived.status == BookingStatus.COMPLETED
        assert survived.fee_charged == 2500

    def test_review_rating_preserved_but_text_anonymised(
        self, session, patient_user, patient_profile, verified_doctor, completed_booking
    ):
        review = Review(
            booking_id=completed_booking.id,
            patient_profile_id=patient_profile.id,
            doctor_id=verified_doctor.id,
            rating=4,
            comment="Dr. sahib was thorough about my diabetes",
            moderation_status=ReviewModerationStatus.APPROVED,
        )
        session.add(review)
        session.commit()

        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        session.refresh(review)
        # The rating stays: dropping it would silently move the doctor's
        # public aggregate (spec.md changelog item 3).
        assert review.rating == 4
        assert review.comment is None

    def test_audit_log_rows_are_retained(self, session, patient_user):
        session.add(
            AuditLog(
                actor_user_id=patient_user.id,
                action="medical_history_read",
                resource_type="patient_profile",
                resource_id=patient_user.id,
            )
        )
        session.commit()

        account_deletion_service.request_deletion(session, user=patient_user)
        account_deletion_service.purge_account(session, user=patient_user)

        # Retained: they reference IDs and actions, never health content.
        remaining = session.exec(select(AuditLog).where(AuditLog.actor_user_id == patient_user.id)).all()
        assert len(remaining) == 1


class TestPurgeSweep:
    def test_does_not_purge_inside_the_grace_window(self, session, patient_user):
        account_deletion_service.request_deletion(session, user=patient_user)

        assert sweep_purgeable_accounts(session) == 0
        session.refresh(patient_user)
        assert patient_user.purged_at is None

    def test_purges_once_the_window_has_passed(self, session, patient_user):
        account_deletion_service.request_deletion(session, user=patient_user)
        patient_user.purge_after = now_utc() - timedelta(seconds=1)
        session.add(patient_user)
        session.commit()

        assert sweep_purgeable_accounts(session) == 1
        session.refresh(patient_user)
        assert patient_user.purged_at is not None
        assert patient_user.full_name == ANONYMISED_NAME

    def test_never_touches_a_live_account(self, session, patient_user, patient_profile):
        assert sweep_purgeable_accounts(session) == 0
        session.refresh(patient_user)
        assert patient_user.is_active is True
        assert patient_user.full_name != ANONYMISED_NAME

    def test_sweep_is_idempotent_across_restarts(self, session, patient_user):
        account_deletion_service.request_deletion(session, user=patient_user)
        patient_user.purge_after = now_utc() - timedelta(seconds=1)
        session.add(patient_user)
        session.commit()

        assert sweep_purgeable_accounts(session) == 1
        # A second tick (or a restart mid-sweep) must not re-purge.
        assert sweep_purgeable_accounts(session) == 0
