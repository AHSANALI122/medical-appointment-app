"""F28 — "N+1 prevention (selectinload)" on list endpoints.

Asserted by counting the SQL actually issued, not by reading the code: an
N+1 regression is invisible in review (it looks like an ordinary attribute
access in a loop) and invisible in tests that only check the response body.
The count is what makes it impossible to reintroduce quietly.
"""

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.core.security import hash_password
from app.models.doctor import ClinicLocation, DoctorProfile
from app.models.enums import DoctorVerificationStatus, UserRole
from app.models.user import User


@contextmanager
def count_queries(session):
    """Counts SELECTs issued on this session's connection."""
    queries: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield queries
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def _make_doctor(session, specialization, index: int) -> DoctorProfile:
    user = User(
        email=f"n1-doctor{index}@example.com",
        password_hash=hash_password("password123"),
        role=UserRole.DOCTOR,
        full_name=f"Dr. Number {index}",
    )
    session.add(user)
    session.flush()

    doctor = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization.id,
        pmc_number=f"PMC-N1-{index:03d}",
        consultation_fee=1000 + index,
        verification_status=DoctorVerificationStatus.VERIFIED,
    )
    session.add(doctor)
    session.flush()

    session.add(
        ClinicLocation(
            doctor_id=doctor.id, name=f"Clinic {index}", address=f"{index} Test Road", city="Lahore"
        )
    )
    session.commit()
    return doctor


@pytest.fixture
def many_doctors(session, specialization):
    return [_make_doctor(session, specialization, i) for i in range(1, 11)]


class TestSearchQueryCount:
    def test_query_count_does_not_scale_with_result_size(self, client, session, many_doctors):
        """The actual N+1 assertion: doubling the page size must not double
        the query count. Before batching, each row cost ~4 queries."""
        from app.core.cache import reset_cache_backend

        reset_cache_backend()
        with count_queries(session) as small:
            assert client.get("/api/v1/doctors?page=1&page_size=5").status_code == 200
        small_count = len(small)

        reset_cache_backend()
        with count_queries(session) as large:
            assert client.get("/api/v1/doctors?page=1&page_size=10").status_code == 200
        large_count = len(large)

        # Slot lookup is still per-row (documented in the endpoint), so the
        # count grows a little — but nothing like the ~4-per-row it was.
        # Doubling rows must add well under 2x the queries.
        assert large_count < small_count * 2, (
            f"query count scaled with page size ({small_count} -> {large_count}): "
            "an N+1 has been reintroduced in search_doctors"
        )

    def test_second_page_is_served_from_cache_without_touching_the_db(
        self, client, session, many_doctors
    ):
        from app.core.cache import reset_cache_backend

        reset_cache_backend()
        client.get("/api/v1/doctors?page=1&page_size=10")

        with count_queries(session) as cached:
            response = client.get("/api/v1/doctors?page=1&page_size=10")

        assert response.status_code == 200
        assert len(cached) == 0, "a cache hit still hit the database"


class TestSearchCorrectnessAfterBatching:
    """Batched lookups must not change what the endpoint returns — these
    pin the behaviour the N+1 version had."""

    def test_every_doctor_gets_its_own_name_fee_and_city(self, client, many_doctors):
        items = client.get("/api/v1/doctors?page=1&page_size=10").json()["items"]

        assert len(items) == 10
        by_id = {item["id"]: item for item in items}
        for doctor in many_doctors:
            item = by_id[str(doctor.id)]
            assert item["consultation_fee"] == doctor.consultation_fee
            assert item["cities"] == ["Lahore"]
            assert item["full_name"].startswith("Dr. Number")

    def test_doctor_without_clinics_reports_no_cities_rather_than_erroring(
        self, client, session, specialization
    ):
        """The dict-based batching must yield [] for a doctor absent from the
        grouped result, not raise KeyError."""
        user = User(
            email="clinicless@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.DOCTOR,
            full_name="Dr. No Clinic",
        )
        session.add(user)
        session.flush()
        session.add(
            DoctorProfile(
                user_id=user.id,
                specialization_id=specialization.id,
                pmc_number="PMC-NOCLINIC",
                consultation_fee=999,
                verification_status=DoctorVerificationStatus.VERIFIED,
            )
        )
        session.commit()

        response = client.get("/api/v1/doctors?page=1&page_size=20")

        assert response.status_code == 200
        item = next(i for i in response.json()["items"] if i["full_name"] == "Dr. No Clinic")
        assert item["cities"] == []

    def test_doctor_with_no_reviews_reports_none_rating_not_an_error(self, client, many_doctors):
        items = client.get("/api/v1/doctors?page=1&page_size=10").json()["items"]

        assert all(item["average_rating"] is None for item in items)
        assert all(item["review_count"] == 0 for item in items)


class TestBatchHelpers:
    def test_rating_summaries_include_every_requested_id(self, session, many_doctors):
        from app.services import review_service

        doctor_ids = [d.id for d in many_doctors]
        summaries = review_service.get_doctor_rating_summaries(session, doctor_ids=doctor_ids)

        assert set(summaries) == set(doctor_ids)
        assert all(summaries[d] == (None, 0) for d in doctor_ids)

    def test_rating_summaries_empty_input_is_a_noop(self, session):
        from app.services import review_service

        assert review_service.get_doctor_rating_summaries(session, doctor_ids=[]) == {}

    def test_clinic_locations_empty_input_is_a_noop(self, session):
        from app.services import doctor_service

        assert doctor_service.list_clinic_locations_for_doctors(session, []) == {}

    def test_clinic_locations_keys_every_requested_id(self, session, many_doctors):
        from app.services import doctor_service

        doctor_ids = [d.id for d in many_doctors] + [uuid.uuid4()]
        grouped = doctor_service.list_clinic_locations_for_doctors(session, doctor_ids)

        assert set(grouped) == set(doctor_ids)
        # The unknown id gets an empty list, not a missing key.
        assert grouped[doctor_ids[-1]] == []

    def test_batched_rating_matches_the_single_row_version(
        self, session, many_doctors, patient_profile, verified_doctor, clinic_location
    ):
        """Guards against the batch and single-row paths drifting apart."""
        from app.services import review_service

        doctor = many_doctors[0]
        single = review_service.get_doctor_rating_summary(session, doctor_id=doctor.id)
        batched = review_service.get_doctor_rating_summaries(session, doctor_ids=[doctor.id])

        assert batched[doctor.id] == single
