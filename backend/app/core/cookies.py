import secrets

from fastapi import Response

from app.api.deps import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.core.config import get_settings

settings = get_settings()


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> str:
    """Set the session + CSRF cookies and return the CSRF token value.

    In production the frontend is served from a different site (Vercel) than the
    API (Hugging Face), so the cookies must be `SameSite=None; Secure` to ride
    along on cross-site fetches. Locally (dev, same-site) we keep `Lax` since
    `None` would require `Secure`, which doesn't work over plain http.

    The CSRF token is returned so the caller can echo it in the `X-CSRF-Token`
    response header — a cross-site frontend can't read the (backend-domain)
    cookie via `document.cookie`, so the header is how it learns the value.
    """
    secure = settings.is_production
    same_site = "none" if secure else "lax"
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        secure=secure,
        samesite=same_site,
        max_age=settings.access_token_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite=same_site,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/",
    )
    # Double-submit CSRF token (F15): deliberately NOT httponly. Same-origin the
    # frontend reads it from the cookie; cross-site it reads it from the
    # X-CSRF-Token response header (the cookie still travels for the server-side
    # cookie-vs-header compare in core/csrf.py).
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite=same_site,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/",
    )
    return csrf_token


def issue_csrf_cookie(existing: str | None, response: Response) -> str:
    """Return the caller's existing CSRF token, or mint + set a fresh one.

    Backs GET /auth/csrf: a reloaded cross-site frontend has lost the token from
    memory and can't read the backend-domain cookie via document.cookie, so it
    asks the API to hand the value back (in the body + X-CSRF-Token header)."""
    if existing:
        return existing
    secure = settings.is_production
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=False,
        secure=secure,
        samesite="none" if secure else "lax",
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/",
    )
    return token


def clear_auth_cookies(response: Response) -> None:
    # Match the samesite/secure attributes the cookies were set with, or the
    # browser won't clear a SameSite=None; Secure cookie.
    secure = settings.is_production
    same_site = "none" if secure else "lax"
    for name in (ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, CSRF_COOKIE_NAME):
        response.delete_cookie(name, path="/", secure=secure, samesite=same_site)
