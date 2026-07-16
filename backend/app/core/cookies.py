import secrets

from fastapi import Response

from app.api.deps import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.core.config import get_settings

settings = get_settings()


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    secure = settings.is_production
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/",
    )
    # Double-submit CSRF token (F15): deliberately NOT httponly — the
    # frontend must be able to read it and echo it back in the
    # X-CSRF-Token header on mutating requests (see core/csrf.py).
    response.set_cookie(
        CSRF_COOKIE_NAME,
        secrets.token_urlsafe(32),
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
