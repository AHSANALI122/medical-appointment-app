from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FeatureFlag(SQLModel, table=True):
    """F20 — minimal admin-toggleable flag, so 'feature-flagged
    independently' (F20's acceptance criterion) is real without building out
    F29's full admin flag UI yet. Reused as-is once F29 lands."""

    __tablename__ = "feature_flags"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    key: str = Field(index=True, unique=True, nullable=False)
    enabled: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
