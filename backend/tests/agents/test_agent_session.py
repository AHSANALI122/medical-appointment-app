from app.models.enums import AgentRole
from app.services import agent_session_service


def test_get_or_create_session_is_idempotent_per_user(session, patient_user):
    first = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
    second = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
    assert first.id == second.id


def test_append_message_round_trips_through_encryption(session, patient_user):
    agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
    secret = "pait mein dard hai, kal se"
    agent_session_service.append_message(
        session, agent_session=agent_session, role=AgentRole.USER, content=secret
    )

    # Read back through a fresh query (not the same in-memory object) to
    # prove the round trip goes through the DB's EncryptedString column,
    # not just Python object identity.
    from sqlmodel import select

    from app.models.agent import AgentMessage

    session.expire_all()
    row = session.exec(select(AgentMessage).where(AgentMessage.session_id == agent_session.id)).one()
    assert row.content == secret


def test_multi_turn_history_survives_across_calls(session, patient_user):
    agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
    agent_session_service.append_message(session, agent_session=agent_session, role=AgentRole.USER, content="hello")
    agent_session_service.append_message(
        session, agent_session=agent_session, role=AgentRole.ASSISTANT, content="hi there", agent_name="Triage Agent"
    )

    messages, total = agent_session_service.list_messages(session, agent_session=agent_session, offset=0, limit=50)
    assert total == 2
    assert [m.role for m in messages] == [AgentRole.USER, AgentRole.ASSISTANT]

    history = agent_session_service.history_as_text(messages)
    assert history == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi there"}]


def test_append_message_audit_logs_write(session, patient_user):
    from sqlmodel import select

    from app.models.audit_log import AuditLog

    agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
    message = agent_session_service.append_message(
        session, agent_session=agent_session, role=AgentRole.USER, content="test"
    )

    log = session.exec(
        select(AuditLog).where(AuditLog.resource_type == "agent_message", AuditLog.resource_id == message.id)
    ).first()
    assert log is not None
    assert log.action == "write"
    assert log.actor_user_id == patient_user.id


def test_set_active_profile_rejects_foreign_profile(session, patient_user):
    from app.core.exceptions import ForbiddenError

    from tests.conftest import make_patient

    agent_session = agent_session_service.get_or_create_session(session, user_id=patient_user.id)
    foreign_profile = make_patient(session, "foreign@example.com")

    try:
        agent_session_service.set_active_profile(
            session, agent_session=agent_session, user_id=patient_user.id, patient_profile_id=foreign_profile.id
        )
        raise AssertionError("expected ForbiddenError")
    except ForbiddenError:
        pass
