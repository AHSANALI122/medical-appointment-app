"""F27 — account deletion (a patient's right), in two stages.

Stage 1 (`request_deletion`, immediate): soft-delete. `is_active` goes
False so every existing auth path (deps.get_current_user,
auth_service.authenticate/refresh_session) already rejects the account
without needing new checks, and `purge_after` is stamped 30 days out. The
grace period exists so an accidental — or coerced — deletion is
recoverable.

Stage 2 (`purge_account`, after 30 days, driven by jobs/purge_sweep.py):
irreversible.

The shape of stage 2 is dictated by referential integrity, not preference.
`bookings.patient_profile_id` and `reviews.patient_profile_id` are NOT NULL
FKs to `patient_profiles`, and spec.md requires both bookings (doctor's
history intact) and review ratings (doctor's aggregate must not silently
change) to survive. So the `User` and `PatientProfile` rows are **kept and
scrubbed**, not deleted — the identity is destroyed, the skeleton the
doctor's records hang from is not. Deleting the profile rows instead would
either cascade the doctor's history away or leave dangling FKs.

  Hard-deleted : agent chat, medical history, patient notes, clinical
                 notes, notifications, waitlist entries, follow-ups,
                 refresh tokens
  Anonymised   : users row, patient_profiles rows, review text
  Preserved    : bookings, review ratings, audit_logs
"""

import uuid
from datetime import timedelta

from sqlmodel import Session, delete, select

from app.core.exceptions import PolicyViolationError
from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.agent import AgentMessage, AgentSession
from app.models.booking import Booking
from app.models.enums import UserRole
from app.models.followup import FollowUp
from app.models.medical_history import MedicalHistory
from app.models.note import ClinicalNote, PatientNote
from app.models.notification import Notification
from app.models.review import Review
from app.models.user import PatientProfile, RefreshToken, User
from app.models.waitlist import Waitlist

logger = get_logger(__name__)

PURGE_GRACE_PERIOD = timedelta(days=30)
ANONYMISED_NAME = "Deleted user"


def _anonymised_email(user_id: uuid.UUID) -> str:
    # `users.email` is UNIQUE, so a constant placeholder would collide on
    # the second purge. `.invalid` is reserved by RFC 2606 and can never
    # route anywhere real.
    return f"deleted+{user_id}@medbook.invalid"


def request_deletion(session: Session, *, user: User) -> User:
    """Soft-delete. Reversible for 30 days via `cancel_deletion`."""
    if user.role != UserRole.PATIENT:
        # Doctors carry clinical records and active appointments; deleting
        # one is an admin/offboarding workflow with its own rules, not this
        # self-service path. spec.md F27 scopes this to the patient right.
        raise PolicyViolationError("only patient accounts can be self-deleted")

    if user.deleted_at is not None:
        return user  # Idempotent — re-requesting doesn't extend the window.

    now = now_utc()
    user.deleted_at = now
    user.purge_after = now + PURGE_GRACE_PERIOD
    user.is_active = False
    user.updated_at = now
    session.add(user)

    # Revoke sessions immediately — a soft-deleted account that still has a
    # live refresh token isn't deleted in any sense the user would recognise.
    for token in session.exec(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    ).all():
        token.revoked_at = now
        session.add(token)

    session.commit()
    session.refresh(user)
    logger.info("account.deletion_requested", user_id=str(user.id), purge_after=user.purge_after.isoformat())
    return user


def cancel_deletion(session: Session, *, user: User) -> User:
    """Undo within the grace window. Purged accounts are gone for good.

    Support-mediated, not self-service: `request_deletion` sets
    `is_active=False`, so the owner cannot log in to reach this themselves.
    That's the deliberate trade — the alternative is teaching every auth
    path to distinguish "deactivated because deleted" from "deactivated
    because banned" and letting the former log in, which is a subtle
    security branch to get wrong for a rare action. Exposed to admins via
    POST /api/v1/admin/users/{id}/restore.
    """
    if user.purged_at is not None:
        raise PolicyViolationError("this account has already been purged and cannot be restored")
    if user.deleted_at is None:
        return user

    user.deleted_at = None
    user.purge_after = None
    user.is_active = True
    user.updated_at = now_utc()
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("account.deletion_cancelled", user_id=str(user.id))
    return user


def purge_account(session: Session, *, user: User) -> None:
    """Irreversible. Called by the sweep once `purge_after` has passed."""
    if user.deleted_at is None:
        raise PolicyViolationError("cannot purge an account that was never deleted")
    if user.purged_at is not None:
        return  # Idempotent — a re-run of the sweep must not double-scrub.

    profile_ids = [
        p.id for p in session.exec(select(PatientProfile).where(PatientProfile.user_id == user.id)).all()
    ]

    _hard_delete_health_data(session, user=user, profile_ids=profile_ids)
    _anonymise_reviews(session, profile_ids=profile_ids)
    _anonymise_profiles(session, profile_ids=profile_ids)
    _anonymise_user(session, user=user)

    session.commit()
    logger.info(
        "account.purged",
        user_id=str(user.id),
        profiles_anonymised=len(profile_ids),
        # Deliberately no email/name in this line — the whole point was to
        # remove them; logging them here would just relocate the PII.
    )


def _hard_delete_health_data(session: Session, *, user: User, profile_ids: list[uuid.UUID]) -> None:
    booking_ids = []
    if profile_ids:
        booking_ids = [
            b.id
            for b in session.exec(
                select(Booking).where(Booking.patient_profile_id.in_(profile_ids))
            ).all()
        ]

    # Chat (encrypted symptoms — health data per CLAUDE.md rule 7).
    agent_session_ids = [
        s.id for s in session.exec(select(AgentSession).where(AgentSession.user_id == user.id)).all()
    ]
    if agent_session_ids:
        session.exec(delete(AgentMessage).where(AgentMessage.session_id.in_(agent_session_ids)))
        session.exec(delete(AgentSession).where(AgentSession.id.in_(agent_session_ids)))

    if profile_ids:
        session.exec(delete(MedicalHistory).where(MedicalHistory.patient_profile_id.in_(profile_ids)))
        session.exec(delete(PatientNote).where(PatientNote.patient_profile_id.in_(profile_ids)))
        session.exec(delete(Waitlist).where(Waitlist.patient_profile_id.in_(profile_ids)))
        session.exec(delete(FollowUp).where(FollowUp.patient_profile_id.in_(profile_ids)))

    # Clinical notes key off booking_id + doctor_id, not patient_profile_id
    # — they'd survive a profile-scoped delete and keep this patient's
    # health data alive under the doctor's records. spec.md F27 lists notes
    # as hard-deleted, so they go with the patient's bookings.
    if booking_ids:
        session.exec(delete(ClinicalNote).where(ClinicalNote.booking_id.in_(booking_ids)))

    session.exec(delete(Notification).where(Notification.user_id == user.id))
    session.exec(delete(RefreshToken).where(RefreshToken.user_id == user.id))


def _anonymise_reviews(session: Session, *, profile_ids: list[uuid.UUID]) -> None:
    if not profile_ids:
        return
    for review in session.exec(select(Review).where(Review.patient_profile_id.in_(profile_ids))).all():
        # Free text can name people or describe a condition; the rating is
        # a bare integer and is what the doctor's public aggregate is built
        # from. Dropping the row would move that aggregate — a side effect
        # the doctor never consented to and can't see. So: text out, score
        # stays (spec.md changelog item 3).
        review.comment = None
        review.updated_at = now_utc()
        session.add(review)


def _anonymise_profiles(session: Session, *, profile_ids: list[uuid.UUID]) -> None:
    if not profile_ids:
        return
    for profile in session.exec(select(PatientProfile).where(PatientProfile.id.in_(profile_ids))).all():
        profile.full_name = ANONYMISED_NAME
        profile.date_of_birth = None
        profile.is_active = False
        session.add(profile)


def _anonymise_user(session: Session, *, user: User) -> None:
    user.email = _anonymised_email(user.id)
    user.full_name = ANONYMISED_NAME
    user.phone = None
    # Not a valid bcrypt hash, so verify_password can never match it —
    # rather than leaving the old hash sitting there recoverable.
    user.password_hash = "purged"
    user.is_active = False
    user.purged_at = now_utc()
    user.updated_at = now_utc()
    session.add(user)


def list_accounts_due_for_purge(session: Session) -> list[User]:
    return list(
        session.exec(
            select(User).where(
                User.purge_after.is_not(None),
                User.purge_after <= now_utc(),
                User.purged_at.is_(None),
            )
        ).all()
    )
