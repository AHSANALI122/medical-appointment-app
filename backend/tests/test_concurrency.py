"""F3 acceptance: 10 parallel booking attempts on the same slot, exactly 1 succeeds.

Each thread opens its own DB connection/session (mirroring real concurrent
requests) and races to create a draft for the same (doctor, clinic, start
time) but a distinct patient. The partial UNIQUE index on `bookings` is the
only thing preventing a double-book — there is no app-level check-then-insert
lock to race around.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from sqlmodel import Session

from app.core.exceptions import SlotUnavailableError
from app.core.security import hash_password
from app.core.timezone import now_utc
from app.models.enums import UserRole
from app.models.user import PatientProfile, User
from app.services.state_machine import BookingStateMachine

N_CONCURRENT = 10


def test_ten_parallel_bookings_exactly_one_succeeds(
    test_engine, session, verified_doctor, clinic_location
):
    patient_ids = []
    for i in range(N_CONCURRENT):
        user = User(
            email=f"racer{i}@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.PATIENT,
            full_name=f"Racer {i}",
        )
        session.add(user)
        session.flush()
        profile = PatientProfile(user_id=user.id, full_name=user.full_name, relationship_label="self")
        session.add(profile)
        session.commit()
        session.refresh(profile)
        patient_ids.append(profile.id)

    start = now_utc() + timedelta(hours=1)
    end = start + timedelta(minutes=30)

    def attempt(patient_id):
        with Session(test_engine) as thread_session:
            machine = BookingStateMachine(thread_session)
            try:
                booking = machine.create_draft(
                    patient_profile_id=patient_id,
                    doctor_id=verified_doctor.id,
                    clinic_location_id=clinic_location.id,
                    start_time_utc=start,
                    end_time_utc=end,
                    fee_charged=verified_doctor.consultation_fee,
                    address_snapshot="123 Main Blvd, Lahore",
                )
                return ("ok", booking.id)
            except SlotUnavailableError:
                return ("conflict", None)

    results = []
    with ThreadPoolExecutor(max_workers=N_CONCURRENT) as executor:
        futures = [executor.submit(attempt, pid) for pid in patient_ids]
        for future in as_completed(futures):
            results.append(future.result())

    successes = [r for r in results if r[0] == "ok"]
    conflicts = [r for r in results if r[0] == "conflict"]

    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}: {results}"
    assert len(conflicts) == N_CONCURRENT - 1
