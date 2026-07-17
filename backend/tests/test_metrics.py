"""F26 — latency percentiles (core/metrics.py), booking funnel counters
(services/funnel_service.py), and the admin-gated /metrics surface."""

from datetime import timedelta

import pytest

from app.core.metrics import LatencyRegistry, _percentile
from app.core.timezone import now_utc
from app.models.enums import BookingSource, BookingStatus
from app.services import funnel_service
from app.services.state_machine import BookingStateMachine


class TestPercentile:
    def test_nearest_rank_on_known_distribution(self):
        values = [float(n) for n in range(1, 101)]  # 1..100
        assert _percentile(values, 50) == 50.0
        assert _percentile(values, 95) == 95.0
        assert _percentile(values, 99) == 99.0

    def test_single_sample_is_every_percentile(self):
        assert _percentile([7.0], 50) == 7.0
        assert _percentile([7.0], 99) == 7.0


class TestLatencyRegistry:
    def test_snapshot_reports_per_endpoint_percentiles(self):
        registry = LatencyRegistry()
        for n in range(1, 101):
            registry.record("GET /api/v1/doctors", float(n))
        registry.record("POST /api/v1/bookings", 5.0)

        snapshot = {row.endpoint: row for row in registry.snapshot()}

        assert snapshot["GET /api/v1/doctors"].count == 100
        assert snapshot["GET /api/v1/doctors"].p50_ms == 50.0
        assert snapshot["GET /api/v1/doctors"].p95_ms == 95.0
        assert snapshot["POST /api/v1/bookings"].count == 1

    def test_ring_buffer_is_bounded(self):
        from app.core.metrics import MAX_SAMPLES_PER_ENDPOINT

        registry = LatencyRegistry()
        for n in range(MAX_SAMPLES_PER_ENDPOINT + 500):
            registry.record("GET /x", float(n))

        (row,) = registry.snapshot()
        assert row.count == MAX_SAMPLES_PER_ENDPOINT

    def test_snapshot_sorts_slowest_first(self):
        registry = LatencyRegistry()
        registry.record("GET /fast", 1.0)
        registry.record("GET /slow", 900.0)

        assert [r.endpoint for r in registry.snapshot()] == ["GET /slow", "GET /fast"]


@pytest.fixture
def make_booking(session, patient_profile, specialization, verified_doctor, clinic_location):
    """Each booking gets its own doctor + clinic.

    Not incidental: the state machine allows only one active draft per
    (profile, doctor) and 3 per profile, so a cohort built against a single
    doctor raises BookingConflictError on the second draft. Reusing one
    doctor would test the abuse guard, not the funnel.
    """
    from app.core.security import hash_password
    from app.models.doctor import ClinicLocation, DoctorProfile
    from app.models.enums import DoctorVerificationStatus, UserRole
    from app.models.user import User

    counter = {"n": 0}

    def _fresh_doctor():
        n = counter["n"]
        user = User(
            email=f"funnel-doctor{n}@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name=f"Dr. Funnel {n}",
        )
        session.add(user)
        session.flush()
        doctor = DoctorProfile(
            user_id=user.id,
            specialization_id=specialization.id,
            pmc_number=f"PMC-FUNNEL-{n:03d}",
            consultation_fee=2000,
            verification_status=DoctorVerificationStatus.VERIFIED,
        )
        session.add(doctor)
        session.flush()
        clinic = ClinicLocation(
            doctor_id=doctor.id, name=f"Clinic {n}", address="123 Main Blvd", city="Lahore"
        )
        session.add(clinic)
        session.commit()
        return doctor, clinic

    def _make(**overrides):
        counter["n"] += 1
        doctor, clinic = _fresh_doctor()
        start = now_utc() + timedelta(hours=counter["n"])
        machine = BookingStateMachine(session)
        return machine.create_draft(
            patient_profile_id=patient_profile.id,
            doctor_id=doctor.id,
            clinic_location_id=clinic.id,
            start_time_utc=start,
            end_time_utc=start + timedelta(minutes=30),
            fee_charged=2000,
            address_snapshot="123 Main Blvd, Lahore",
            **overrides,
        )

    return _make


class TestBookingFunnel:
    def test_draft_only_counts_at_first_stage(self, session, make_booking):
        make_booking()

        funnel = funnel_service.get_booking_funnel(session)

        assert funnel.reached_draft == 1
        assert funnel.reached_pending == 0
        assert funnel.reached_confirmed == 0
        assert funnel.draft_to_pending_rate == 0.0

    def test_confirmed_booking_counts_at_every_stage_it_passed(self, session, make_booking):
        machine = BookingStateMachine(session)
        booking = make_booking()
        machine.confirm(booking)
        machine.doctor_accept(booking)

        funnel = funnel_service.get_booking_funnel(session)

        assert funnel.reached_draft == 1
        assert funnel.reached_pending == 1
        assert funnel.reached_confirmed == 1
        assert funnel.draft_to_confirmed_rate == 1.0

    def test_completed_booking_still_counts_as_reached_confirmed(self, session, make_booking):
        """Counting by *current* status would miss this — the whole reason
        the funnel reads timestamps instead."""
        machine = BookingStateMachine(session)
        booking = make_booking()
        machine.confirm(booking)
        machine.doctor_accept(booking)
        booking.start_time_utc = now_utc() - timedelta(hours=1)
        machine.mark_completed(booking)

        funnel = funnel_service.get_booking_funnel(session)

        assert booking.status == BookingStatus.COMPLETED
        assert funnel.reached_confirmed == 1
        assert funnel.reached_pending == 1

    def test_draft_expired_never_reached_pending(self, session, make_booking):
        machine = BookingStateMachine(session)
        booking = make_booking()
        machine.expire(booking)

        funnel = funnel_service.get_booking_funnel(session)

        assert funnel.reached_draft == 1
        assert funnel.reached_pending == 0

    def test_pending_expired_did_reach_pending(self, session, make_booking):
        """The case current-status counting cannot distinguish from the one
        above: both rows end up 'expired', but this one converted a step."""
        machine = BookingStateMachine(session)
        booking = make_booking()
        machine.confirm(booking)
        machine.expire(booking)

        funnel = funnel_service.get_booking_funnel(session)

        assert booking.status == BookingStatus.EXPIRED
        assert funnel.reached_pending == 1
        assert funnel.reached_confirmed == 0

    def test_system_waitlist_holds_excluded_from_funnel(self, session, make_booking):
        make_booking(source=BookingSource.SYSTEM_WAITLIST)

        funnel = funnel_service.get_booking_funnel(session)

        assert funnel.reached_draft == 0

    def test_conversion_rates_across_a_mixed_cohort(self, session, make_booking):
        machine = BookingStateMachine(session)
        # Target cohort: 4 drafts, 2 of which reach pending, 1 of those
        # reaching confirmed.
        #
        # The ordering below is forced by the abuse guard: a profile may hold
        # at most 3 *active* (draft|pending) bookings, so b3 has to be driven
        # all the way to confirmed — which is not an active status — before
        # there's room to create b4.
        make_booking()  # stays draft
        make_booking()  # stays draft
        b3 = make_booking()
        machine.confirm(b3)  # -> pending
        machine.doctor_accept(b3)  # -> confirmed, frees an active slot

        b4 = make_booking()
        machine.confirm(b4)  # -> pending

        funnel = funnel_service.get_booking_funnel(session)

        assert funnel.reached_draft == 4
        assert funnel.reached_pending == 2
        assert funnel.reached_confirmed == 1
        assert funnel.draft_to_pending_rate == 0.5
        assert funnel.pending_to_confirmed_rate == 0.5
        assert funnel.draft_to_confirmed_rate == 0.25

    def test_empty_cohort_reports_zero_not_division_error(self, session):
        funnel = funnel_service.get_booking_funnel(session)

        assert funnel.reached_draft == 0
        assert funnel.draft_to_pending_rate == 0.0
        assert funnel.pending_to_confirmed_rate == 0.0


def _login(client, email, password="password123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200


def _register_admin(session, email="metrics-admin@example.com"):
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User

    user = User(
        email=email, password_hash=hash_password("password123"), role=UserRole.ADMIN, full_name="Admin User"
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class TestMetricsEndpoint:
    def test_unauthenticated_gets_401(self, client_factory):
        assert client_factory().get("/api/v1/metrics").status_code == 401

    def test_patient_gets_403(self, client_factory, patient_user):
        client = client_factory()
        _login(client, patient_user.email)
        assert client.get("/api/v1/metrics").status_code == 403

    def test_admin_gets_latency_funnel_and_spend(self, client_factory, session):
        admin_user = _register_admin(session)
        client = client_factory()
        _login(client, admin_user.email)

        response = client.get("/api/v1/metrics")

        assert response.status_code == 200
        body = response.json()
        assert "latency" in body
        assert "funnel" in body
        assert body["llm_spend"]["status"] == "ok"
        assert body["llm_spend"]["budget"] > 0

    def test_middleware_records_the_request_it_just_served(self, client_factory, session):
        from app.core.metrics import get_latency_registry

        get_latency_registry().reset()
        admin_user = _register_admin(session, email="metrics-admin2@example.com")
        client = client_factory()
        _login(client, admin_user.email)
        client.get("/api/v1/metrics")

        endpoints = [row.endpoint for row in get_latency_registry().snapshot()]
        # Keyed by route template, not raw path.
        assert "GET /api/v1/metrics" in endpoints


class TestRouteTemplate:
    """Endpoint keys must be the *full* templated path. This FastAPI version
    nests included routers, so the matched route only knows its leaf
    (`/{doctor_id}`) — keying off that would merge every router's `/me` into
    one bucket, and bucket ids individually would blow up cardinality."""

    def test_ids_collapse_into_one_bucket(self, client_factory, verified_doctor):
        from app.core.metrics import get_latency_registry

        get_latency_registry().reset()
        client = client_factory()
        client.get(f"/api/v1/doctors/{verified_doctor.id}")
        client.get("/api/v1/doctors/00000000-0000-0000-0000-000000000000")

        by_endpoint = {row.endpoint: row for row in get_latency_registry().snapshot()}
        assert by_endpoint["GET /api/v1/doctors/{doctor_id}"].count == 2

    def test_same_leaf_under_different_routers_stays_separate(self, client_factory):
        from app.core.metrics import get_latency_registry

        get_latency_registry().reset()
        client = client_factory()
        client.get("/api/v1/doctors/me")
        client.get("/api/v1/bookings/me")

        endpoints = {row.endpoint for row in get_latency_registry().snapshot()}
        assert "GET /api/v1/doctors/me" in endpoints
        assert "GET /api/v1/bookings/me" in endpoints

    def test_unmatched_paths_collapse_rather_than_mint_a_series_each(self, client_factory):
        from app.core.metrics import get_latency_registry

        get_latency_registry().reset()
        client = client_factory()
        client.get("/no-such-route")
        client.get("/another/bogus/path")

        by_endpoint = {row.endpoint: row for row in get_latency_registry().snapshot()}
        assert by_endpoint["GET unmatched"].count == 2
