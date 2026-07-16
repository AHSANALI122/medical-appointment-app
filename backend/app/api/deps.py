import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import InvalidTokenError, TokenType, decode_token
from app.models.enums import UserRole
from app.models.user import PatientProfile, User

ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise UnauthorizedError("not authenticated")

    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise UnauthorizedError("invalid or expired session") from exc

    user = session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("account not found or disabled")

    return user


def require_role(*roles: UserRole) -> Callable[[User], User]:
    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError(f"requires role in {[r.value for r in roles]}")
        return user

    return _dependency


require_patient = require_role(UserRole.PATIENT)
require_doctor = require_role(UserRole.DOCTOR)
require_admin = require_role(UserRole.ADMIN)


def resolve_self_patient_profile(session: Session, user: User) -> PatientProfile:
    """Resolves a patient User's own 'self' PatientProfile. Family-account
    profile switching (F20) will extend this with an explicit active-profile
    selector; for now every patient has exactly one 'self' profile, and it is
    always resolved from the JWT-owned user_id — never from client-supplied
    input."""
    profile = session.exec(
        select(PatientProfile).where(
            PatientProfile.user_id == user.id, PatientProfile.relationship_label == "self"
        )
    ).first()
    if profile is None:
        raise NotFoundError("patient profile not found")
    return profile


def get_active_patient_profile(
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> PatientProfile:
    return resolve_self_patient_profile(session, user)


def resolve_owned_patient_profile(session: Session, user: User, profile_id: uuid.UUID) -> PatientProfile:
    """F20 family accounts: resolves *any* of the JWT-owned user's profiles
    (self or a dependent), never a client-supplied profile outside that
    set — same ownership-validation shape as `set_active_profile_tool`
    (agents/tools.py) uses for the agent-side equivalent."""
    profile = session.get(PatientProfile, profile_id)
    if profile is None or profile.user_id != user.id:
        raise ForbiddenError("that patient profile does not belong to you")
    return profile
