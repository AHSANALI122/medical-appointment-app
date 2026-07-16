import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(SQLModel, table=True):
    """Append-only record of who read/wrote sensitive health data (clinical
    notes, patient notes, and eventually F24 medical history), per CLAUDE.md
    rule 7 and F15. Rows are never updated or deleted by application code."""

    __tablename__ = "audit_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    action: str = Field(index=True, nullable=False, max_length=100)
    resource_type: str = Field(index=True, nullable=False, max_length=100)
    resource_id: uuid.UUID = Field(index=True, nullable=False)
    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False, index=True))
