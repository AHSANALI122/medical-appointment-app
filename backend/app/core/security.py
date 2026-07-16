import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()

# bcrypt's own algorithm silently truncates at 72 bytes; passlib's wrapper
# raises instead of truncating, so we hash the raw bcrypt module directly.
_BCRYPT_MAX_BYTES = 72


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, password_hash.encode("ascii"))


def _create_token(
    *, subject: str, token_type: TokenType, ttl: timedelta, extra_claims: dict[str, Any] | None = None
) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + ttl,
        "jti": jti,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def create_access_token(user_id: str, role: str) -> tuple[str, str]:
    return _create_token(
        subject=user_id,
        token_type=TokenType.ACCESS,
        ttl=timedelta(minutes=settings.access_token_ttl_minutes),
        extra_claims={"role": role},
    )


def create_refresh_token(user_id: str) -> tuple[str, str]:
    return _create_token(
        subject=user_id,
        token_type=TokenType.REFRESH,
        ttl=timedelta(days=settings.refresh_token_ttl_days),
    )


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError(f"expected token type {expected_type.value!r}, got {payload.get('type')!r}")

    return payload
