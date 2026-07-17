from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import utc_datetime_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DailyLLMUsage(SQLModel, table=True):
    """F26 — per-provider daily token spend, one row per (date, provider),
    upserted on every agent/summary LLM call. DB-backed (not in-memory) so
    the daily budget survives process restarts, matching CLAUDE.md's TTL
    rule that budget-relevant counters live in the DB, not scheduler state."""

    __tablename__ = "daily_llm_usage"
    __table_args__ = (UniqueConstraint("usage_date", "provider", name="uq_daily_llm_usage_date_provider"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    usage_date: date = Field(index=True, nullable=False)
    provider: str = Field(index=True, nullable=False)
    requests: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
