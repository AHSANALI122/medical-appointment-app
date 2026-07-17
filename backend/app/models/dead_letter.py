import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeadLetterJob(SQLModel, table=True):
    """F22 — dead-letter queue for jobs that keep failing (reminders today;
    any future job can reuse it). `job_type` + `reference_id` identify what
    failed (e.g. 'reminder', booking_id); `attempt_count` is bumped on each
    retry. `alerted_at` is set once a repeat-failure alert has been logged,
    so the same job doesn't page/log critical on every sweep tick."""

    __tablename__ = "dead_letter_jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_type: str = Field(index=True, nullable=False)
    reference_id: uuid.UUID = Field(index=True, nullable=False)
    error: str
    attempt_count: int = Field(default=1)
    first_failed_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    last_failed_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    resolved_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
    alerted_at: datetime | None = Field(default=None, sa_column=utc_datetime_column(nullable=True))
