"""F20 — daily sweep for `deferred` follow-ups whose target date has now
entered the 60-day booking horizon. Polling-based, same idempotency shape as
the F3/F12 sweeps: a follow-up already `notified` simply doesn't match the
`deferred` filter anymore, so re-running this is always safe.
"""

from sqlmodel import Session

from app.core.logging import get_logger
from app.services.followup_service import sweep_deferred_followups

logger = get_logger(__name__)


def run_followup_sweep(session: Session) -> int:
    count = sweep_deferred_followups(session)
    if count:
        logger.info("followup_sweep.completed", notified_count=count)
    return count
