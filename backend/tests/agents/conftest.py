import json
import uuid

import pytest
from agents.tool_context import ToolContext

from app.agents.context import MedBookAgentContext
from app.models.agent import AgentSession


@pytest.fixture
def agent_session(session, patient_user):
    from app.services import agent_session_service

    return agent_session_service.get_or_create_session(session, user_id=patient_user.id)


@pytest.fixture
def agent_context(session, patient_user, patient_profile, agent_session: AgentSession):
    return MedBookAgentContext(
        session=session,
        user_id=patient_user.id,
        agent_session_id=agent_session.id,
        active_patient_profile_id=patient_profile.id,
    )


@pytest.fixture
def fake_llm(monkeypatch):
    """Installs a scripted `FakeModel` in place of the real LitellmModel
    lookup, so `runner.run_agent_turn` (and anything going through
    `app.llm.client.ResilientModelRouter`) never makes a network call.
    Per CLAUDE.md: mock all LLM calls in unit tests."""
    import app.llm.client as llm_client

    from tests.agents.fake_model import FakeModel

    def _install(responses):
        model = FakeModel(responses)
        monkeypatch.setattr(llm_client, "get_agent_model", lambda provider: model)
        return model

    yield _install
    llm_client.get_circuit_breaker().reset()


async def invoke_tool(tool, context: MedBookAgentContext, **kwargs) -> dict:
    """Calls a `@function_tool`-wrapped function directly, the same way the
    Agents SDK would during a real run, without needing any LLM call."""
    tool_ctx = ToolContext(
        context=context,
        tool_name=tool.name,
        tool_call_id=f"call_{uuid.uuid4().hex[:8]}",
        tool_arguments=json.dumps(kwargs),
    )
    raw = await tool.on_invoke_tool(tool_ctx, json.dumps(kwargs))
    return json.loads(raw) if isinstance(raw, str) else raw
