from typing import Any

from sqlalchemy import Column, DateTime


def utc_datetime_column(**column_kwargs: Any) -> Column:
    """Postgres TIMESTAMPTZ column. Without timezone=True, psycopg returns
    naive datetimes on read, which then blow up comparisons against
    timezone-aware `now_utc()` everywhere in the booking state machine."""
    return Column(DateTime(timezone=True), **column_kwargs)
