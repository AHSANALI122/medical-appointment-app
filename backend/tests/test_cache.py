"""F28 — doctor profile/search caching.

The load-bearing tests here are the invalidation ones. A cache that serves
a stale consultation fee is not a performance win: F7 snapshots
`fee_charged` onto the draft at creation, so a patient booking off a stale
cached price gets that wrong price written onto their booking permanently.
"""


import httpx

from app.core.cache import InMemoryCache, UpstashRedisCache, get_cache, reset_cache_backend
from app.services import doctor_cache


class TestInMemoryCache:
    def test_round_trips_a_value(self):
        cache = InMemoryCache()
        cache.set("k", {"a": 1}, ttl_seconds=60)
        assert cache.get("k") == {"a": 1}

    def test_missing_key_is_none(self):
        assert InMemoryCache().get("nope") is None

    def test_expired_entry_reads_as_a_miss(self, monkeypatch):
        cache = InMemoryCache()
        clock = {"now": 1000.0}
        monkeypatch.setattr("app.core.cache.time.monotonic", lambda: clock["now"])

        cache.set("k", "v", ttl_seconds=60)
        clock["now"] += 61

        assert cache.get("k") is None

    def test_delete_prefix_only_clears_the_prefix(self):
        cache = InMemoryCache()
        cache.set("doctor:search:a", 1, ttl_seconds=60)
        cache.set("doctor:search:b", 2, ttl_seconds=60)
        cache.set("doctor:profile:x", 3, ttl_seconds=60)

        cache.delete_prefix("doctor:search:")

        assert cache.get("doctor:search:a") is None
        assert cache.get("doctor:search:b") is None
        assert cache.get("doctor:profile:x") == 3


class TestBackendSelection:
    def test_defaults_to_in_memory_without_upstash_configured(self):
        reset_cache_backend()
        assert isinstance(get_cache(), InMemoryCache)

    def test_uses_upstash_when_configured(self, monkeypatch):
        from app.core import cache as cache_module

        class _FakeSettings:
            upstash_redis_url = "https://example.upstash.io"
            upstash_redis_token = "tok"  # noqa: S105 — fake

        reset_cache_backend()
        monkeypatch.setattr(cache_module, "get_settings", lambda: _FakeSettings())
        assert isinstance(get_cache(), UpstashRedisCache)
        reset_cache_backend()


class TestUpstashDegradesGracefully:
    """A cache outage must degrade to "slow but correct", never to a 500 —
    hence get() swallowing errors and reporting a miss."""

    def test_get_reports_a_miss_when_upstash_is_unreachable(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise httpx.ConnectError("upstash is down")

        monkeypatch.setattr(httpx, "get", _boom)
        cache = UpstashRedisCache(url="https://example.upstash.io", token="tok")

        assert cache.get("k") is None  # not an exception

    def test_set_swallows_errors(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise httpx.ConnectError("upstash is down")

        monkeypatch.setattr(httpx, "post", _boom)
        cache = UpstashRedisCache(url="https://example.upstash.io", token="tok")

        cache.set("k", "v", ttl_seconds=60)  # must not raise

    def test_corrupt_value_reads_as_a_miss(self, monkeypatch):
        class _Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"result": "not-json{{"}

        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Response())
        cache = UpstashRedisCache(url="https://example.upstash.io", token="tok")

        assert cache.get("k") is None


class TestSearchKey:
    def test_same_filters_produce_the_same_key(self):
        a = doctor_cache.search_key(city="Lahore", page=1)
        b = doctor_cache.search_key(page=1, city="Lahore")
        assert a == b  # order-independent

    def test_different_filters_produce_different_keys(self):
        assert doctor_cache.search_key(city="Lahore") != doctor_cache.search_key(city="Karachi")

    def test_free_text_names_cannot_break_the_key(self):
        """`name` is user input and reaches an Upstash REST *path*; hashing
        keeps it opaque and bounded."""
        key = doctor_cache.search_key(name="../../etc/passwd?x=1 #frag")
        assert key.startswith(doctor_cache.SEARCH_PREFIX)
        suffix = key.removeprefix(doctor_cache.SEARCH_PREFIX)
        assert suffix.isalnum()


class TestEndpointCaching:
    def test_profile_is_served_from_cache_on_the_second_call(self, client, verified_doctor):
        first = client.get(f"/api/v1/doctors/{verified_doctor.id}")
        assert first.status_code == 200
        assert doctor_cache.get_profile(verified_doctor.id) is not None

        second = client.get(f"/api/v1/doctors/{verified_doctor.id}")
        assert second.status_code == 200
        assert second.json() == first.json()

    def test_fee_change_invalidates_immediately_not_after_the_ttl(
        self, client_factory, session, verified_doctor
    ):
        """The one that matters: a stale fee gets snapshotted onto a booking
        (F7) and becomes a support ticket."""
        patient = client_factory()
        assert patient.get(f"/api/v1/doctors/{verified_doctor.id}").json()["consultation_fee"] == 1500

        doctor = client_factory()
        doctor.post("/api/v1/auth/login", json={"email": "doctor@example.com", "password": "password123"})
        updated = doctor.patch("/api/v1/doctors/me", json={"consultation_fee": 3500})
        assert updated.status_code == 200

        assert patient.get(f"/api/v1/doctors/{verified_doctor.id}").json()["consultation_fee"] == 3500

    def test_profile_edit_also_clears_cached_search_pages(
        self, client_factory, session, verified_doctor
    ):
        patient = client_factory()
        patient.get("/api/v1/doctors")
        # Something is cached under the search namespace now.
        doctor = client_factory()
        doctor.post("/api/v1/auth/login", json={"email": "doctor@example.com", "password": "password123"})
        doctor.patch("/api/v1/doctors/me", json={"consultation_fee": 4100})

        results = patient.get("/api/v1/doctors").json()["items"]
        fees = [r["consultation_fee"] for r in results if r["id"] == str(verified_doctor.id)]
        assert fees == [4100]

    def test_search_results_round_trip_through_the_cache_unchanged(self, client, verified_doctor):
        first = client.get("/api/v1/doctors").json()
        second = client.get("/api/v1/doctors").json()
        # Second is deserialized from cached JSON — proves the Page model
        # survives model_dump(mode="json") -> model_validate.
        assert second == first
