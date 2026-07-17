"""F22 — dead-letter queue for jobs that fail to deliver (reminders today;
any future job/notification path can reuse it).

The reminder sweep (jobs/reminders.py) logs a `ReminderLog` row *before*
calling the notifier so a crash never double-sends — which also means a
failed send is not retried on the next tick (the log already makes it look
"done" to `_already_sent`). Retrying that exact send is a bigger
architectural change than F22 asks for here; what this module gives
instead is visibility: every failure is recorded, and `maybe_alert` raises
a single structured log line once failures for a job type cross a
threshold in a rolling window, so a provider outage shows up as one alert
rather than silently dropping N reminders.
"""

import uuid
from datetime import timedelta

from sqlmodel import Session, func, select

from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.dead_letter import DeadLetterJob

logger = get_logger(__name__)

ALERT_THRESHOLD = 3
ALERT_WINDOW = timedelta(hours=1)


def record_failure(session: Session, *, job_type: str, reference_id: uuid.UUID, error: str) -> DeadLetterJob:
    entry = DeadLetterJob(job_type=job_type, reference_id=reference_id, error=error)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def maybe_alert(session: Session, *, job_type: str) -> bool:
    """Returns True and logs a critical alert if unalerted failures for
    `job_type` within ALERT_WINDOW have reached ALERT_THRESHOLD. Marks those
    rows alerted so the same batch of failures doesn't re-alert next tick."""
    cutoff = now_utc() - ALERT_WINDOW
    unalerted = list(
        session.exec(
            select(DeadLetterJob).where(
                DeadLetterJob.job_type == job_type,
                DeadLetterJob.alerted_at.is_(None),
                DeadLetterJob.last_failed_at >= cutoff,
            )
        ).all()
    )
    if len(unalerted) < ALERT_THRESHOLD:
        return False

    logger.critical(
        "dead_letter.repeat_failures",
        job_type=job_type,
        failure_count=len(unalerted),
        window_hours=ALERT_WINDOW.total_seconds() / 3600,
    )
    now = now_utc()
    for entry in unalerted:
        entry.alerted_at = now
        session.add(entry)
    session.commit()
    return True


def count_unresolved(session: Session, *, job_type: str) -> int:
    return session.exec(
        select(func.count()).where(DeadLetterJob.job_type == job_type, DeadLetterJob.resolved_at.is_(None))
    ).one()
