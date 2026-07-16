"""F15 — CSRF protection on cookie auth via the double-submit pattern.

`set_auth_cookies` (core/cookies.py) issues a non-httponly `csrf_token`
cookie alongside the httponly access/refresh tokens. Any mutating request
made while an auth cookie is present must echo that token back in the
`X-CSRF-Token` header — a cross-site form/fetch can make the browser attach
cookies automatically, but it cannot read the cookie's value to set the
header, since it's a different origin.
"""

import hmac
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.deps import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME, REFRESH_COOKIE_NAME
from app.core.request_context import get_request_id

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _MUTATING_METHODS:
            has_session = bool(
                request.cookies.get(ACCESS_COOKIE_NAME) or request.cookies.get(REFRESH_COOKIE_NAME)
            )
            if has_session:
                cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
                header_token = request.headers.get(CSRF_HEADER_NAME)
                if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error_code": "csrf_failed",
                            "message": "missing or invalid CSRF token",
                            "request_id": get_request_id(request),
                        },
                    )

        return await call_next(request)
