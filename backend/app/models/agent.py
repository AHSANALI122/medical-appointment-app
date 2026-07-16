import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from app.core.db_types import utc_datetime_column
from app.core.encryption import EncryptedString
from app.models.enums import AgentRole, enum_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentSession(SQLModel, table=True):
    """Server-side conversation session for the F17 multi-agent assistant.
    One per user (the triage/booking/reschedule/FAQ entry point); multi-turn
    context survives a page refresh because history lives here, not in
    browser state. `active_patient_profile_id` is the family-account
    selector (F20) — set only via the `set_active_profile` tool, which
    validates ownership against the JWT's user_id, never trusts LLM input."""

    __tablename__ = "agent_sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    active_patient_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="patient_profiles.id", index=True
    )

    created_at: datetime = Field(default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False))
    last_activity_at: datetime = Field(
        default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False)
    )


class AgentMessage(SQLModel, table=True):
    """A single turn in an `AgentSession`. Content is Fernet-encrypted
    (CLAUDE.md rule 7) — patients type symptoms into chat, making this health
    data exactly like clinical notes. Retention: 12 months then purge (a
    future sweep job); `agent_name` records which sub-agent produced an
    assistant turn, for debugging/tracing only."""

    __tablename__ = "agent_messages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="agent_sessions.id", index=True, nullable=False)

    role: AgentRole = Field(sa_column=enum_column(AgentRole, nullable=False))
    content: str = Field(sa_type=EncryptedString)
    agent_name: str | None = None

    created_at: datetime = Field(
        default_factory=_utcnow, sa_column=utc_datetime_column(nullable=False, index=True)
    )
