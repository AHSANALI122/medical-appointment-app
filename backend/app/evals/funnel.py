"""F21/F26 — booking funnel counters against real data. Every booking is a
`draft` at creation, so total row count is the funnel's top; `confirmed_at
IS NOT NULL` is exactly "ever reached confirmed" regardless of what it later
became (completed, cancelled, no_show) — cheaper and more accurate than
inferring from current `status`, since a `cancelled` booking can have gotten
there from either `pending` or `confirmed` (see state_machine.py's legal
transitions) and only the timestamp actually disambiguates that.
"""

from sqlmodel import Session, func, select

from app.evals.metrics import booking_completion_rate
from app.models.booking import Booking


def compute_booking_completion_rate(session: Session) -> float:
    total_drafts = session.exec(select(func.count()).select_from(Booking)).one()
    ever_confirmed = session.exec(
        select(func.count()).where(Booking.confirmed_at.is_not(None))
    ).one()
    return booking_completion_rate(drafts=total_drafts, confirmed=ever_confirmed)
