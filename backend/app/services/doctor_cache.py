"""F28 — cache keys and invalidation for the doctor directory.

Only public directory data lives here: a doctor's own `/doctors/me` view is
deliberately never cached (a doctor must see their own edit immediately, and
it's a single-row read on an indexed FK — there's nothing to save).

Invalidation is prefix-based: one profile edit clears that doctor's profile
key *and* the entire search namespace, because a fee or city change moves
that doctor across an unknowable set of cached filter/sort/page
combinations. Enumerating which cached searches a given edit affects is not
worth it at this scale — search entries live 60s and are cheap to refill.
Stale prices are not: a patient who books at a fee the doctor no longer
charges is a support ticket, and F7's snapshot rule means we'd have written
that stale fee onto the booking.
"""

import hashlib
import uuid
from typing import Any

from app.core.cache import (
    DOCTOR_PROFILE_TTL_SECONDS,
    SEARCH_RESULTS_TTL_SECONDS,
    get_cache,
)

PROFILE_PREFIX = "doctor:profile:"
SEARCH_PREFIX = "doctor:search:"


def profile_key(doctor_id: uuid.UUID) -> str:
    return f"{PROFILE_PREFIX}{doctor_id}"


def search_key(**filters: Any) -> str:
    """Hashes the filter set so the key stays a bounded length and can't
    contain characters that would break the Upstash REST path (a free-text
    `name` filter is user input and could contain anything)."""
    canonical = "|".join(f"{k}={filters[k]}" for k in sorted(filters))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    return f"{SEARCH_PREFIX}{digest}"


def get_profile(doctor_id: uuid.UUID) -> dict | None:
    return get_cache().get(profile_key(doctor_id))


def set_profile(doctor_id: uuid.UUID, payload: dict) -> None:
    get_cache().set(profile_key(doctor_id), payload, ttl_seconds=DOCTOR_PROFILE_TTL_SECONDS)


def get_search(key: str) -> dict | None:
    return get_cache().get(key)


def set_search(key: str, payload: dict) -> None:
    get_cache().set(key, payload, ttl_seconds=SEARCH_RESULTS_TTL_SECONDS)


def invalidate_doctor(doctor_id: uuid.UUID) -> None:
    """Called on every write that changes what a patient would see: profile
    edits, clinic add/edit, and admin verification changes (an unverified
    doctor must not linger in a cached search page)."""
    cache = get_cache()
    cache.delete_prefix(profile_key(doctor_id))
    cache.delete_prefix(SEARCH_PREFIX)
