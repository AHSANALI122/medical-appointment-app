"""Timezone rule (global, per spec.md): all timestamps stored UTC; all display
and slot generation happen in Asia/Karachi. No client-local-time math on
booking-critical paths — conversions live here, in one place."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

KARACHI_TZ = ZoneInfo("Asia/Karachi")
UTC = ZoneInfo("UTC")


def local_to_utc(local_dt: datetime) -> datetime:
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=KARACHI_TZ)
    return local_dt.astimezone(UTC)


def utc_to_local(utc_dt: datetime) -> datetime:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(KARACHI_TZ)


def combine_local(local_date: date, local_time: time) -> datetime:
    return datetime.combine(local_date, local_time, tzinfo=KARACHI_TZ)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_local() -> datetime:
    return datetime.now(KARACHI_TZ)
