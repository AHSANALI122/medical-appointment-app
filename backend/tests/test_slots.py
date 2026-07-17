import uuid
from datetime import time, timedelta

from app.core.timezone import now_local, utc_to_local
from app.models.doctor import AvailabilityRule
from app.services.slot_service import (
    _WEEKDAY_BY_INDEX,
    generate_available_slots,
    is_within_booking_window,
    next_available_slot_for_doctor,
    next_available_slot_for_doctors,
)

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


class TestNextAvailableSlotBatching:
    """The batched next-slot lookup re-implements the day-walk that
    `generate_available_slots` does (to gain an early exit), so these pin the
    two paths together — a divergence here is a silently wrong search page."""

    def test_batched_matches_the_single_row_version(
        self, session, verified_doctor, clinic_location, availability_rule
    ):
        single = next_available_slot_for_doctor(session, doctor_id=verified_doctor.id)
        batched = next_available_slot_for_doctors(session, doctor_ids=[verified_doctor.id])

        assert batched[verified_doctor.id] == single
        assert single is not None

    def test_batched_returns_the_earliest_generated_slot(
        self, session, verified_doctor, clinic_location, availability_rule
    ):
        today = now_local().date()
        slots = generate_available_slots(
            session,
            doctor_id=verified_doctor.id,
            clinic_location_id=clinic_location.id,
            from_date=today,
            to_date=today + timedelta(days=_WINDOW_DAYS),
        )
        batched = next_available_slot_for_doctors(session, doctor_ids=[verified_doctor.id])

        assert batched[verified_doctor.id] == slots[0].start_time_utc

    def test_every_requested_id_gets_a_key(self, session, verified_doctor):
        unknown = uuid.uuid4()
        batched = next_available_slot_for_doctors(
            session, doctor_ids=[verified_doctor.id, unknown]
        )

        assert set(batched) == {verified_doctor.id, unknown}
        assert batched[unknown] is None

    def test_empty_input_is_a_noop(self, session):
        assert next_available_slot_for_doctors(session, doctor_ids=[]) == {}

    def test_doctor_wide_exception_fans_out_to_every_location(
        self, session, verified_doctor, clinic_location, availability_rule
    ):
        """A NULL clinic_location_id exception must suppress today's slots at
        every clinic, not just the one it happens to be grouped under."""
        from app.models.doctor import AvailabilityException, ClinicLocation

        second = ClinicLocation(
            doctor_id=verified_doctor.id,
            name="Second Clinic",
            address="9 Other Road",
            city="Lahore",
        )
        session.add(second)
        session.commit()
        session.refresh(second)
        session.add(
            AvailabilityRule(
                doctor_id=verified_doctor.id,
                clinic_location_id=second.id,
                weekday=_WEEKDAY_BY_INDEX[now_local().date().weekday()],
                start_time_local=time(0, 0),
                end_time_local=time(23, 45),
                slot_duration_minutes=30,
            )
        )
        today = now_local().date()
        session.add(
            AvailabilityException(
                doctor_id=verified_doctor.id, exception_date=today, reason="leave"
            )
        )
        session.commit()

        batched = next_available_slot_for_doctors(session, doctor_ids=[verified_doctor.id])

        earliest = batched[verified_doctor.id]
        assert earliest is not None
        assert utc_to_local(earliest).date() != today

    def test_location_scoped_exception_leaves_the_other_clinic_bookable(
        self, session, verified_doctor, clinic_location, availability_rule
    ):
        from app.models.doctor import AvailabilityException

        today = now_local().date()
        session.add(
            AvailabilityException(
                doctor_id=verified_doctor.id,
                clinic_location_id=clinic_location.id,
                exception_date=today,
                reason="leave",
            )
        )
        session.commit()

        batched = next_available_slot_for_doctors(session, doctor_ids=[verified_doctor.id])

        # Only clinic; the scoped exception removes today for this doctor.
        earliest = batched[verified_doctor.id]
        assert earliest is not None
        assert utc_to_local(earliest).date() != today
