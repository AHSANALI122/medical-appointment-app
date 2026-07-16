"""F15 — Rate limiting on auth, booking, and (once F17 lands) /chat endpoints.

In-process fixed-window limiter by default — the same "stub-able in dev,
swap via env" pattern CLAUDE.md already establishes for email/SMS
(notification_service._send_email_stub). Swapping the backing store for
Upstash Redis in production means implementing `RateLimiter` against the
Upstash REST API and swapping what `get_rate_limiter()` returns; call sites
never change. A single in-process counter is a real limitation on a
multi-instance deployment (Railway can run >1 instance) — acceptable for v1
where a single instance is expected, called out here rather than hidden.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Request

from app.core.exceptions import RateLimitExceededError


@dataclass
class _Window:
    count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class RateLimiter:
    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.window_start >= window_seconds:
                window = _Window(count=0, window_start=now)
                self._windows[key] = window
            window.count += 1
            return window.count <= limit

    def reset(self) -> None:
        """Test-only escape hatch — the limiter is process-global by design."""
        with self._lock:
            self._windows.clear()


_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _limiter


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(tier: str, *, limit: int, window_seconds: int) -> Callable[[Request], None]:
    """FastAPI dependency factory. Keyed by client IP — auth endpoints have
    no authenticated identity yet, and a uniform key strategy keeps the
    per-tier tuning (auth strictest, booking next, chat strictest once F17
    lands per spec.md F15) in one obvious place."""

    def _dependency(request: Request) -> None:
        key = f"{tier}:{_client_key(request)}"
        if not get_rate_limiter().allow(key, limit=limit, window_seconds=window_seconds):
            raise RateLimitExceededError("too many requests — please try again shortly")

    return _dependency


# Tiers, per F15: chat is strictest of all (LLM calls are the most expensive
# resource), auth next, booking most permissive.
AUTH_RATE_LIMIT = ("auth", 10, 60)
BOOKING_RATE_LIMIT = ("booking", 30, 60)
CHAT_RATE_LIMIT = ("chat", 5, 60)
