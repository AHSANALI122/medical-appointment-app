import uuid
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.core.timezone import UTC, combine_local, now_local, now_utc
from app.models.booking import Booking
from app.models.doctor import AvailabilityException, AvailabilityRule, ClinicLocation
from app.models.enums import SLOT_HOLDING_STATUSES, Weekday
from app.schemas.doctor import SlotRead

MIN_LEAD_TIME = timedelta(minutes=30)
MAX_HORIZON = timedelta(days=60)

# Bound for the F10 search "next available slot" lookup — deliberately short
# (vs. the full 60-day booking horizon) so it stays cheap per search result
# row; a doctor with nothing open in 2 weeks just shows no next slot.
_NEXT_SLOT_LOOKUP_WINDOW = timedelta(days=14)

_WEEKDAY_BY_INDEX = {
    0: Weekday.MON,
    1: Weekday.TUE,
    2: Weekday.WED,
    3: Weekday.THU,
    4: Weekday.FRI,
    5: Weekday.SAT,
    6: Weekday.SUN,
}


def is_within_booking_window(start_time_utc: datetime) -> bool:
    now = now_utc()
    return now + MIN_LEAD_TIME <= start_time_utc <= now + MAX_HORIZON


def generate_available_slots(
    session: Session,
    *,
    doctor_id,
    clinic_location_id,
    from_date: date,
    to_date: date,
) -> list[SlotRead]:
    """Dynamically generates candidate slots from recurring availability rules,
    applies leave/holiday exceptions, then filters out anything already held
    by an active booking. Slots have no row of their own — this is a pure
    read-side projection; the only durable conflict guard is the partial
    UNIQUE index on `bookings`, enforced at insert time."""

    if to_date < from_date:
        return []

    rules = session.exec(
        select(AvailabilityRule).where(
            AvailabilityRule.doctor_id == doctor_id,
            AvailabilityRule.clinic_location_id == clinic_location_id,
            AvailabilityRule.is_active == True,  # noqa: E712
        )
    ).all()
    if not rules:
        return []

    rules_by_weekday: dict[Weekday, list[AvailabilityRule]] = {}
    for rule in rules:
        rules_by_weekday.setdefault(rule.weekday, []).append(rule)

    exceptions = session.exec(
        select(AvailabilityException).where(
            AvailabilityException.doctor_id == doctor_id,
            AvailabilityException.exception_date >= from_date,
            AvailabilityException.exception_date <= to_date,
        )
    ).all()
    excepted_dates: set[date] = {
        exc.exception_date
        for exc in exceptions
        if exc.clinic_location_id is None or exc.clinic_location_id == clinic_location_id
    }

    range_start_utc = combine_local(from_date, datetime.min.time())
    range_end_utc = combine_local(to_date + timedelta(days=1), datetime.min.time())
    booked_starts: set[datetime] = set(
        session.exec(
            select(Booking.start_time_utc).where(
                Booking.doctor_id == doctor_id,
                Booking.clinic_location_id == clinic_location_id,
                Booking.status.in_(SLOT_HOLDING_STATUSES),
                Booking.start_time_utc >= range_start_utc,
                Booking.start_time_utc < range_end_utc,
            )
        ).all()
    )

    slots: list[SlotRead] = []
    current = from_date
    while current <= to_date:
        if current not in excepted_dates:
            weekday = _WEEKDAY_BY_INDEX[current.weekday()]
            for rule in rules_by_weekday.get(weekday, []):
                slots.extend(_slots_for_rule(rule, current, booked_starts))
        current += timedelta(days=1)

    slots.sort(key=lambda s: s.start_time_utc)
    return slots


def _slots_for_rule(
    rule: AvailabilityRule, on_date: date, booked_starts: set[datetime]
) -> list[SlotRead]:
    results: list[SlotRead] = []
    cursor_local = combine_local(on_date, rule.start_time_local)
    end_local = combine_local(on_date, rule.end_time_local)
    step = timedelta(minutes=rule.slot_duration_minutes)

    while cursor_local + step <= end_local:
        start_utc = cursor_local.astimezone(UTC)
        end_utc = start_utc + step

        if start_utc not in booked_starts and is_within_booking_window(start_utc):
            results.append(
                SlotRead(
                    clinic_location_id=rule.clinic_location_id,
                    start_time_utc=start_utc,
                    end_time_utc=end_utc,
                )
            )
        cursor_local += step

    return results


def next_available_slot_for_doctor(session: Session, *, doctor_id: uuid.UUID) -> datetime | None:
    """Earliest open slot across all of a doctor's active clinic locations,
    within a short lookahead window (F10 search result field)."""
    return next_available_slot_for_doctors(session, doctor_ids=[doctor_id])[doctor_id]


def next_available_slot_for_doctors(
    session: Session, *, doctor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime | None]:
    """Batched form of `next_available_slot_for_doctor` for list endpoints
    (F28 N+1 prevention): four queries for the whole page instead of one per
    location per doctor. Every requested id gets a key, so a doctor with no
    clinics or no open slots yields None rather than a KeyError.

    The per-doctor scan stops at the first date that yields any slot — dates
    are walked in order, so that date holds the earliest slot and the rest of
    the lookahead window is dead work. That early exit is why this doesn't
    reuse `generate_available_slots`, which must materialise the whole range.
    """
    earliest_by_doctor: dict[uuid.UUID, datetime | None] = {
        doctor_id: None for doctor_id in doctor_ids
    }
    if not doctor_ids:
        return {}

    today = now_local().date()
    to_date = (now_local() + _NEXT_SLOT_LOOKUP_WINDOW).date()

    locations = session.exec(
        select(ClinicLocation).where(
            ClinicLocation.doctor_id.in_(doctor_ids),
            ClinicLocation.is_active == True,  # noqa: E712
        )
    ).all()
    if not locations:
        return earliest_by_doctor

    location_ids = [location.id for location in locations]
    locations_by_doctor: dict[uuid.UUID, list[ClinicLocation]] = {}
    for location in locations:
        locations_by_doctor.setdefault(location.doctor_id, []).append(location)

    rules = session.exec(
        select(AvailabilityRule).where(
            AvailabilityRule.clinic_location_id.in_(location_ids),
            AvailabilityRule.is_active == True,  # noqa: E712
        )
    ).all()
    rules_by_location: dict[uuid.UUID, dict[Weekday, list[AvailabilityRule]]] = {}
    for rule in rules:
        by_weekday = rules_by_location.setdefault(rule.clinic_location_id, {})
        by_weekday.setdefault(rule.weekday, []).append(rule)

    exceptions = session.exec(
        select(AvailabilityException).where(
            AvailabilityException.doctor_id.in_(doctor_ids),
            AvailabilityException.exception_date >= today,
            AvailabilityException.exception_date <= to_date,
        )
    ).all()
    # A NULL clinic_location_id means the exception covers the whole doctor
    # (leave/holiday), so it has to fan out to each of their locations.
    excepted_dates_by_location: dict[uuid.UUID, set[date]] = {
        location_id: set() for location_id in location_ids
    }
    for exc in exceptions:
        for location in locations_by_doctor.get(exc.doctor_id, []):
            if exc.clinic_location_id is None or exc.clinic_location_id == location.id:
                excepted_dates_by_location[location.id].add(exc.exception_date)

    range_start_utc = combine_local(today, datetime.min.time())
    range_end_utc = combine_local(to_date + timedelta(days=1), datetime.min.time())
    booked_by_location: dict[uuid.UUID, set[datetime]] = {
        location_id: set() for location_id in location_ids
    }
    booked_rows = session.exec(
        select(Booking.clinic_location_id, Booking.start_time_utc).where(
            Booking.clinic_location_id.in_(location_ids),
            Booking.status.in_(SLOT_HOLDING_STATUSES),
            Booking.start_time_utc >= range_start_utc,
            Booking.start_time_utc < range_end_utc,
        )
    ).all()
    for location_id, start_time_utc in booked_rows:
        booked_by_location[location_id].add(start_time_utc)

    for doctor_id in doctor_ids:
        earliest_by_doctor[doctor_id] = _earliest_slot_for_locations(
            locations_by_doctor.get(doctor_id, []),
            rules_by_location=rules_by_location,
            excepted_dates_by_location=excepted_dates_by_location,
            booked_by_location=booked_by_location,
            from_date=today,
            to_date=to_date,
        )
    return earliest_by_doctor


def _earliest_slot_for_locations(
    locations: list[ClinicLocation],
    *,
    rules_by_location: dict[uuid.UUID, dict[Weekday, list[AvailabilityRule]]],
    excepted_dates_by_location: dict[uuid.UUID, set[date]],
    booked_by_location: dict[uuid.UUID, set[datetime]],
    from_date: date,
    to_date: date,
) -> datetime | None:
    current = from_date
    while current <= to_date:
        weekday = _WEEKDAY_BY_INDEX[current.weekday()]
        earliest_on_date: datetime | None = None

        for location in locations:
            if current in excepted_dates_by_location[location.id]:
                continue
            for rule in rules_by_location.get(location.id, {}).get(weekday, []):
                for slot in _slots_for_rule(rule, current, booked_by_location[location.id]):
                    if earliest_on_date is None or slot.start_time_utc < earliest_on_date:
                        earliest_on_date = slot.start_time_utc

        if earliest_on_date is not None:
            return earliest_on_date
        current += timedelta(days=1)
    return None
