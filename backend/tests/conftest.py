from collections.abc import Generator
from datetime import time, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import hash_password
from app.core.timezone import now_utc
from app.main import app
from app.models.doctor import AvailabilityRule, ClinicLocation, DoctorProfile
from app.models.enums import DoctorVerificationStatus, UserRole, Weekday
from app.models.taxonomy import SpecializationTaxonomy
from app.models.user import PatientProfile, User

settings = get_settings()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The in-memory rate limiter (core/rate_limit.py) is a process-global
    singleton keyed by client IP, and TestClient's IP is always
    'testclient' — without this, unrelated tests across the whole suite
    would trip each other's 429s just by running in the same 60s window."""
    from app.core.rate_limit import get_rate_limiter

    get_rate_limiter().reset()
    yield


@pytest.fixture(autouse=True)
def _reset_cache():
    """Same hazard as the rate limiter above: the F28 doctor cache
    (core/cache.py) is a process-global singleton with a 60s TTL, while the
    `session` fixture truncates every table between tests. Without this, a
    search cached by one test would still be served to the next one — whose
    DB no longer contains those doctors — and the failure would look like a
    query bug rather than a stale cache."""
    from app.core.cache import reset_cache_backend

    reset_cache_backend()
    yield


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFAwareTestClient(TestClient):
    """Mirrors what the real frontend does (api.ts echoes the non-httponly
    csrf_token cookie back as X-CSRF-Token on mutating requests) so the vast
    majority of tests — which exercise application behavior, not CSRF itself
    — don't need to know the double-submit protocol exists. test_security.py
    uses a plain TestClient to prove the protection actually rejects a
    request that skips this step."""

    def request(self, method, url, **kwargs):
        if method.upper() in _MUTATING_METHODS:
            csrf_token = self.cookies.get("csrf_token")
            if csrf_token:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", csrf_token)
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


def _test_database_url() -> str:
    base = settings.database_url
    assert base.rsplit("/", 1)[-1] != "", "DATABASE_URL must include a database name"
    return base.rsplit("/", 1)[0] + "/medbook_test"


def _admin_dsn() -> str:
    base = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    return base.rsplit("/", 1)[0] + "/postgres"


def _ensure_test_database_exists() -> None:
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'medbook_test'"
        ).fetchone()
        if not exists:
            conn.execute("CREATE DATABASE medbook_test")


@pytest.fixture(scope="session")
def test_engine():
    _ensure_test_database_exists()
    engine = create_engine(_test_database_url())
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def session(test_engine) -> Generator[Session, None, None]:
    with Session(test_engine) as s:
        yield s
    with test_engine.begin() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client(test_engine, session: Session) -> Generator[TestClient, None, None]:
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    with CSRFAwareTestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_factory(test_engine, session: Session) -> Generator[callable, None, None]:
    """Produces independent TestClients (separate cookie jars) sharing the
    same DB session — needed for tests where two authenticated actors
    (e.g. patient + doctor, or two different doctors) interact in one test."""

    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    clients: list[TestClient] = []

    def _make() -> TestClient:
        c = CSRFAwareTestClient(app)
        clients.append(c)
        return c

    yield _make
    app.dependency_overrides.clear()


@pytest.fixture
def specialization(session: Session) -> SpecializationTaxonomy:
    spec = SpecializationTaxonomy(slug="general-physician", name_en="General Physician", name_ur="جنرل فزیشن")
    session.add(spec)
    session.commit()
    session.refresh(spec)
    return spec


@pytest.fixture
def patient_user(session: Session) -> User:
    user = User(
        email="patient@example.com",
        password_hash=hash_password("password123"),
        role=UserRole.PATIENT,
        full_name="Ayesha Khan",
    )
    session.add(user)
    session.flush()
    session.add(PatientProfile(user_id=user.id, full_name=user.full_name, relationship_label="self"))
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def patient_profile(session: Session, patient_user: User) -> PatientProfile:
    return session.exec(
        select(PatientProfile).where(PatientProfile.user_id == patient_user.id)
    ).one()


def make_patient(session: Session, email: str) -> PatientProfile:
    user = User(
        email=email,
        password_hash=hash_password("password123"),
        role=UserRole.PATIENT,
        full_name=email.split("@")[0],
    )
    session.add(user)
    session.flush()
    profile = PatientProfile(user_id=user.id, full_name=user.full_name, relationship_label="self")
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@pytest.fixture
def verified_doctor(session: Session, specialization: SpecializationTaxonomy) -> DoctorProfile:
    user = User(
        email="doctor@example.com",
        password_hash=hash_password("password123"),
        role=UserRole.DOCTOR,
        full_name="Dr. Bilal Ahmed",
    )
    session.add(user)
    session.flush()

    doctor = DoctorProfile(
        user_id=user.id,
        specialization_id=specialization.id,
        pmc_number="PMC-12345",
        consultation_fee=1500,
        verification_status=DoctorVerificationStatus.VERIFIED,
    )
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return doctor


@pytest.fixture
def clinic_location(session: Session, verified_doctor: DoctorProfile) -> ClinicLocation:
    location = ClinicLocation(
        doctor_id=verified_doctor.id,
        name="City Clinic",
        address="123 Main Blvd",
        city="Lahore",
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@pytest.fixture
def availability_rule(
    session: Session, verified_doctor: DoctorProfile, clinic_location: ClinicLocation
) -> AvailabilityRule:
    """Covers every weekday, all day, so slot-generation tests don't flake
    depending on what time of day (or week) the suite happens to run."""
    rules = []
    for weekday in Weekday:
        rule = AvailabilityRule(
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            weekday=weekday,
            start_time_local=time(0, 0),
            end_time_local=time(23, 45),
            slot_duration_minutes=30,
        )
        session.add(rule)
        rules.append(rule)
    session.commit()
    for rule in rules:
        session.refresh(rule)
    return rules[0]


def future_slot_time(minutes_ahead: int = 60) -> "tuple":
    start = now_utc() + timedelta(minutes=minutes_ahead)
    end = start + timedelta(minutes=30)
    return start, end
