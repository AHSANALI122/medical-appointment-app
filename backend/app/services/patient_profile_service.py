"""F20 — family accounts: one User -> multiple PatientProfile records.
Every patient gets a 'self' profile at registration (auth_service); this
module only adds dependents on top of that."""

import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.core.exceptions import PolicyViolationError
from app.models.user import PatientProfile


def create_dependent_profile(
    session: Session,
    *,
    user_id: uuid.UUID,
    full_name: str,
    relationship_label: str,
    date_of_birth: datetime | None,
) -> PatientProfile:
    if relationship_label.strip().lower() == "self":
        raise PolicyViolationError("'self' is reserved for the profile created at registration")

    profile = PatientProfile(
        user_id=user_id, full_name=full_name, relationship_label=relationship_label, date_of_birth=date_of_birth
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def list_profiles_for_user(session: Session, *, user_id: uuid.UUID) -> list[PatientProfile]:
    return list(
        session.exec(
            select(PatientProfile).where(
                PatientProfile.user_id == user_id, PatientProfile.is_active == True  # noqa: E712
            )
        ).all()
    )
