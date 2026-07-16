from datetime import timedelta

from app.core.timezone import now_local, utc_to_local
from app.services.slot_service import generate_available_slots, is_within_booking_window

# availability_rule covers every weekday all day, so a 3-day window always
# contains generatable slots regardless of what time of day the suite runs.
_WINDOW_DAYS = 3


def test_generates_slots_from_availability_rule(
    session, verified_doctor, clinic_location, availability_rule
):
    today = now_local().date()
    slots = generate_available_slots(
        session,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        from_date=today,
        to_date=today + timedelta(days=_WINDOW_DAYS),
    )
    assert len(slots) > 0
    for slot in slots:
        assert is_within_booking_window(slot.start_time_utc)
        assert slot.end_time_utc - slot.start_time_utc == timedelta(minutes=30)


def test_excludes_slot_already_booked(session, verified_doctor, clinic_location, availability_rule):
    from app.services.state_machine import BookingStateMachine
    from tests.conftest import make_patient

    today = now_local().date()
    slots_before = generate_available_slots(
        session,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        from_date=today,
        to_date=today + timedelta(days=_WINDOW_DAYS),
    )
    assert slots_before, "fixture must generate at least one candidate slot"
    target = slots_before[0]

    patient = make_patient(session, "slotbooker@example.com")
    BookingStateMachine(session).create_draft(
        patient_profile_id=patient.id,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        start_time_utc=target.start_time_utc,
        end_time_utc=target.end_time_utc,
        fee_charged=verified_doctor.consultation_fee,
        address_snapshot="addr",
    )

    slots_after = generate_available_slots(
        session,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        from_date=today,
        to_date=today + timedelta(days=_WINDOW_DAYS),
    )
    assert target.start_time_utc not in {s.start_time_utc for s in slots_after}


def test_excludes_dates_with_leave_exception(
    session, verified_doctor, clinic_location, availability_rule
):
    from app.models.doctor import AvailabilityException

    today = now_local().date()
    excepted_date = today + timedelta(days=1)
    session.add(
        AvailabilityException(doctor_id=verified_doctor.id, exception_date=excepted_date, reason="leave")
    )
    session.commit()

    slots = generate_available_slots(
        session,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        from_date=today,
        to_date=today + timedelta(days=_WINDOW_DAYS),
    )
    assert all(utc_to_local(slot.start_time_utc).date() != excepted_date for slot in slots)


def test_no_slots_for_doctor_with_no_availability_rules(session, verified_doctor, clinic_location):
    today = now_local().date()
    slots = generate_available_slots(
        session,
        doctor_id=verified_doctor.id,
        clinic_location_id=clinic_location.id,
        from_date=today,
        to_date=today,
    )
    assert slots == []
