"""F28 — cache for doctor profiles and search results (60s TTL).

Two backends behind one interface, chosen by whether Upstash is configured
— the same "stub-able in dev, swap via env" pattern as core/rate_limit.py
and notification_service._send_email_stub. Call sites never branch on which
one is live.

**A cache failure is never a request failure.** Every operation swallows
backend errors and reports a miss, so an Upstash outage degrades us to
"every read hits Postgres" — slower, still correct — instead of 500ing a
booking flow over a cache lookup. That's the whole reason `get` returns
`None` rather than raising: a miss and an outage are the same thing to the
caller, deliberately.

Never cache anything patient-scoped here. Everything cached is public
directory data (doctor profiles, search listings) that every visitor sees
identically. Health data is encrypted at rest precisely so it doesn't sit
in plaintext in a third-party key-value store (CLAUDE.md rule 7).
"""

import json
import threading
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

DOCTOR_PROFILE_TTL_SECONDS = 60
SEARCH_RESULTS_TTL_SECONDS = 60
_UPSTASH_TIMEOUT_SECONDS = 2.0


class Cache:
    def get(self, key: str) -> Any | None:
        raise NotImplementedError

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError


class InMemoryCache(Cache):
    """Default backend (dev, tests, and single-instance deploys without
    Upstash configured). Process-local, so on a multi-instance deployment
    each instance keeps its own copy and an invalidation only clears the
    instance that served the write — which is exactly why production should
    configure Upstash. Called out here rather than discovered later."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + ttl_seconds, value)

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in [k for k in self._store if k.startswith(prefix)]:
                del self._store[key]

    def reset(self) -> None:
        """Test-only escape hatch — the cache is process-global by design."""
        with self._lock:
            self._store.clear()


class UpstashRedisCache(Cache):
    """Upstash's REST API rather than a redis:// client — it's HTTP, so it
    works from serverless/edge runtimes and needs no connection pool."""

    def __init__(self, *, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    def _request(self, path: str) -> Any | None:
        response = httpx.get(
            f"{self._url}/{path}", headers=self._headers, timeout=_UPSTASH_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json().get("result")

    def get(self, key: str) -> Any | None:
        try:
            raw = self._request(f"get/{key}")
        except Exception as exc:  # noqa: BLE001 — a cache outage must not fail the request
            logger.warning("cache.get_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # A poisoned/legacy value: treat as a miss and let the caller
            # recompute rather than propagating a parse error upward.
            logger.warning("cache.corrupt_value", key=key)
            return None

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        try:
            encoded = json.dumps(value)
            response = httpx.post(
                f"{self._url}/set/{key}",
                params={"EX": ttl_seconds},
                content=encoded,
                headers=self._headers,
                timeout=_UPSTASH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — best-effort write
            logger.warning("cache.set_failed", key=key, error=str(exc))

    def delete_prefix(self, prefix: str) -> None:
        """Upstash has no prefix-delete, so this is SCAN + DEL. Invalidation
        is rare (a doctor editing their profile) and the keyspace is small,
        so the scan cost is acceptable; if that stops being true, switch to
        versioned keys (bump a namespace counter) instead of scanning."""
        try:
            cursor = "0"
            while True:
                result = self._request(f"scan/{cursor}/match/{prefix}*/count/100")
                if not result:
                    return
                cursor, keys = result[0], result[1]
                for key in keys:
                    self._request(f"del/{key}")
                if cursor == "0":
                    return
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache.delete_prefix_failed", prefix=prefix, error=str(exc))


_in_memory_cache = InMemoryCache()
_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is not None:
        return _cache

    settings = get_settings()
    if settings.upstash_redis_url and settings.upstash_redis_token:
        _cache = UpstashRedisCache(
            url=settings.upstash_redis_url, token=settings.upstash_redis_token
        )
        logger.info("cache.backend_selected", backend="upstash")
    else:
        _cache = _in_memory_cache
        logger.info("cache.backend_selected", backend="in_memory")
    return _cache


def reset_cache_backend() -> None:
    """Test-only — clears both the memoised backend choice and any in-memory
    entries, so a test that sets Upstash env vars doesn't leak into the next."""
    global _cache
    _cache = None
    _in_memory_cache.reset()
