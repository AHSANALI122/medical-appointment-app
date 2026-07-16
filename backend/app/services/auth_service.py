import uuid
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.exceptions import UnauthorizedError, ValidationAppError
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.doctor import DoctorProfile
from app.models.enums import DoctorVerificationStatus, UserRole
from app.models.user import PatientProfile, RefreshToken, User


def _issue_tokens(session: Session, user: User) -> tuple[str, str]:
    access_token, _ = create_access_token(str(user.id), user.role.value)
    refresh_token, refresh_jti = create_refresh_token(str(user.id))

    payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    session.add(
        RefreshToken(
            jti=refresh_jti,
            user_id=user.id,
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    )
    session.commit()
    return access_token, refresh_token


def register_patient(
    session: Session, *, email: str, password: str, full_name: str, phone: str | None
) -> User:
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing is not None:
        raise ValidationAppError("an account with this email already exists")

    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole.PATIENT,
        full_name=full_name,
        phone=phone,
    )
    session.add(user)
    session.flush()

    session.add(PatientProfile(user_id=user.id, full_name=full_name, relationship_label="self"))
    session.commit()
    session.refresh(user)
    return user


def register_doctor(
    session: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None,
    pmc_number: str,
    specialization_id: uuid.UUID,
    consultation_fee: int,
) -> tuple[User, DoctorProfile]:
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing is not None:
        raise ValidationAppError("an account with this email already exists")

    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole.DOCTOR,
        full_name=full_name,
        phone=phone,
    )
    session.add(user)
    session.flush()

    doctor_profile = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization_id,
        pmc_number=pmc_number,
        consultation_fee=consultation_fee,
        verification_status=DoctorVerificationStatus.UNVERIFIED,
    )
    session.add(doctor_profile)
    session.commit()
    session.refresh(user)
    session.refresh(doctor_profile)
    return user, doctor_profile


def authenticate(session: Session, *, email: str, password: str) -> User:
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("account disabled")
    return user


def login(session: Session, *, email: str, password: str) -> tuple[User, str, str]:
    user = authenticate(session, email=email, password=password)
    access_token, refresh_token = _issue_tokens(session, user)
    return user, access_token, refresh_token


def refresh_session(session: Session, *, refresh_token: str) -> tuple[User, str, str]:
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except Exception as exc:
        raise UnauthorizedError("invalid or expired refresh token") from exc

    stored = session.exec(
        select(RefreshToken).where(RefreshToken.jti == payload["jti"])
    ).first()
    if stored is None or stored.revoked_at is not None:
        raise UnauthorizedError("refresh token has been revoked")
    if stored.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise UnauthorizedError("refresh token expired")

    user = session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("account not found or disabled")

    # Rotate: revoke the old token, issue a fresh pair.
    stored.revoked_at = datetime.now(timezone.utc)
    session.add(stored)

    new_access_token, new_refresh_token = _issue_tokens(session, user)

    new_payload = decode_token(new_refresh_token, expected_type=TokenType.REFRESH)
    stored.replaced_by_jti = new_payload["jti"]
    session.add(stored)
    session.commit()

    return user, new_access_token, new_refresh_token


def revoke_refresh_token(session: Session, *, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except Exception:
        return

    stored = session.exec(select(RefreshToken).where(RefreshToken.jti == payload["jti"])).first()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)
        session.add(stored)
        session.commit()
