"""F17 — session persistence for the multi-agent assistant. One `AgentSession`
per user, reused across visits (get-or-create), so multi-turn context
survives a page refresh — the server, not the browser, is the source of
truth for chat history. All reads/writes of `AgentMessage` (health data,
CLAUDE.md rule 7) are audit-logged, same as clinical/patient notes.
"""

import uuid

from sqlmodel import Session, select

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.timezone import now_utc
from app.models.agent import AgentMessage, AgentSession
from app.models.enums import AgentRole
from app.models.user import PatientProfile
from app.services import audit_service


def get_or_create_session(session: Session, *, user_id: uuid.UUID) -> AgentSession:
    existing = session.exec(
        select(AgentSession).where(AgentSession.user_id == user_id)
    ).first()
    if existing is not None:
        return existing

    agent_session = AgentSession(user_id=user_id)
    session.add(agent_session)
    session.commit()
    session.refresh(agent_session)
    return agent_session


def get_owned_session(session: Session, *, session_id: uuid.UUID, user_id: uuid.UUID) -> AgentSession:
    agent_session = session.get(AgentSession, session_id)
    if agent_session is None or agent_session.user_id != user_id:
        raise NotFoundError("chat session not found")
    return agent_session


def touch(session: Session, agent_session: AgentSession) -> None:
    agent_session.last_activity_at = now_utc()
    session.add(agent_session)
    session.commit()


def append_message(
    session: Session,
    *,
    agent_session: AgentSession,
    role: AgentRole,
    content: str,
    agent_name: str | None = None,
) -> AgentMessage:
    message = AgentMessage(
        session_id=agent_session.id, role=role, content=content, agent_name=agent_name
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    audit_service.log(
        session,
        actor_user_id=agent_session.user_id,
        action="write",
        resource_type="agent_message",
        resource_id=message.id,
    )
    return message


def list_messages(
    session: Session, *, agent_session: AgentSession, offset: int, limit: int
) -> tuple[list[AgentMessage], int]:
    query = select(AgentMessage).where(AgentMessage.session_id == agent_session.id)
    all_messages = list(session.exec(query.order_by(AgentMessage.created_at.asc())).all())
    page = all_messages[offset : offset + limit]
    for message in page:
        audit_service.log(
            session,
            actor_user_id=agent_session.user_id,
            action="read",
            resource_type="agent_message",
            resource_id=message.id,
        )
    return page, len(all_messages)


def history_as_text(messages: list[AgentMessage]) -> list[dict]:
    """Converts persisted messages into the SDK's input-item shape (plain
    role/content dicts). Tool-call bookkeeping isn't replayed across turns —
    each turn's tool calls are resolved within that turn, only the
    user-visible text needs to survive into the next turn's prompt."""
    return [
        {"role": "user" if m.role == AgentRole.USER else "assistant", "content": m.content}
        for m in messages
        if m.role in (AgentRole.USER, AgentRole.ASSISTANT)
    ]


def set_active_profile(
    session: Session, *, agent_session: AgentSession, user_id: uuid.UUID, patient_profile_id: uuid.UUID
) -> AgentSession:
    """The agent-side equivalent of F20's family-profile selector. Validates
    ownership against the JWT-derived user_id — never trusts the caller
    (whether that's a tool argument the LLM produced, or a client request) —
    per CLAUDE.md rule 8."""
    profile = session.get(PatientProfile, patient_profile_id)
    if profile is None or profile.user_id != user_id:
        raise ForbiddenError("that patient profile does not belong to you")

    agent_session.active_patient_profile_id = patient_profile_id
    session.add(agent_session)
    session.commit()
    session.refresh(agent_session)
    return agent_session
