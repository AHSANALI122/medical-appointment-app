from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.core.timezone import UTC, combine_local, now_utc
from app.models.booking import Booking
from app.models.doctor import AvailabilityException, AvailabilityRule
from app.models.enums import SLOT_HOLDING_STATUSES, Weekday
from app.schemas.doctor import SlotRead

MIN_LEAD_TIME = timedelta(minutes=30)
MAX_HORIZON = timedelta(days=60)

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
