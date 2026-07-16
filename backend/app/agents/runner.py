"""F17 session orchestration: loads prior turns, runs the keyword emergency
fast-path before any LLM call (F19), routes through the resilient
primary/fallback model (llm/client.py), persists the new turns (encrypted,
F17), and surfaces any `draft` booking created this turn so the chat
response can carry structured data for the frontend's HITL confirmation
card (F18).
"""

import uuid
from dataclasses import dataclass

from agents import InputGuardrailTripwireTriggered, RunConfig, Runner
from sqlmodel import Session

from app.agents.context import MedBookAgentContext
from app.agents.triage import triage_agent
from app.core.exceptions import LLMProviderError
from app.core.logging import get_logger
from app.guardrails.emergency import EMERGENCY_MESSAGE, keyword_emergency_check
from app.guardrails.output_scanner import SAFE_FALLBACK_MESSAGE, OutputGuardrailTripwireTriggered
from app.llm.client import get_resilient_router
from app.models.agent import AgentSession
from app.models.enums import AgentRole
from app.models.user import User
from app.services import agent_session_service

logger = get_logger(__name__)

LLM_UNAVAILABLE_MESSAGE = (
    "I'm having trouble connecting right now. Please try again in a moment, "
    "or use the search page to book directly — that always works even when "
    "I'm down."
)


@dataclass
class AgentTurnResult:
    reply: str
    draft_booking_id: uuid.UUID | None
    emergency: bool


async def _call_llm(context: MedBookAgentContext, input_items: list[dict]):
    router = get_resilient_router()

    async def run_fn(model):
        context.resolved_model = model
        return await Runner.run(
            triage_agent, input=input_items, context=context, run_config=RunConfig(model=model)
        )

    return await router.run(run_fn)


async def run_agent_turn(
    session: Session, *, user: User, agent_session: AgentSession, user_message: str
) -> AgentTurnResult:
    active_profile_id = agent_session.active_patient_profile_id
    context = MedBookAgentContext(
        session=session,
        user_id=user.id,
        agent_session_id=agent_session.id,
        active_patient_profile_id=active_profile_id,
    )

    # Zero-latency keyword fast-path (F19): no LLM call at all if it hits.
    if keyword_emergency_check(user_message):
        agent_session_service.append_message(
            session, agent_session=agent_session, role=AgentRole.USER, content=user_message
        )
        agent_session_service.append_message(
            session,
            agent_session=agent_session,
            role=AgentRole.ASSISTANT,
            content=EMERGENCY_MESSAGE,
            agent_name="emergency_keyword_guardrail",
        )
        agent_session_service.touch(session, agent_session)
        logger.info("agent.emergency_keyword_trip", session_id=str(agent_session.id))
        return AgentTurnResult(reply=EMERGENCY_MESSAGE, draft_booking_id=None, emergency=True)

    history, _ = agent_session_service.list_messages(
        session, agent_session=agent_session, offset=0, limit=10_000
    )
    input_items = agent_session_service.history_as_text(history) + [
        {"role": "user", "content": user_message}
    ]

    agent_session_service.append_message(
        session, agent_session=agent_session, role=AgentRole.USER, content=user_message
    )

    try:
        result = await _call_llm(context, input_items)
    except InputGuardrailTripwireTriggered:
        reply = EMERGENCY_MESSAGE
        agent_session_service.append_message(
            session,
            agent_session=agent_session,
            role=AgentRole.ASSISTANT,
            content=reply,
            agent_name="emergency_classifier_guardrail",
        )
        agent_session_service.touch(session, agent_session)
        logger.info("agent.emergency_classifier_trip", session_id=str(agent_session.id))
        return AgentTurnResult(reply=reply, draft_booking_id=None, emergency=True)
    except OutputGuardrailTripwireTriggered:
        reply = SAFE_FALLBACK_MESSAGE
        agent_session_service.append_message(
            session,
            agent_session=agent_session,
            role=AgentRole.ASSISTANT,
            content=reply,
            agent_name="output_guardrail",
        )
        agent_session_service.touch(session, agent_session)
        logger.warning("agent.output_guardrail_trip", session_id=str(agent_session.id))
        return AgentTurnResult(reply=reply, draft_booking_id=None, emergency=False)
    except LLMProviderError:
        reply = LLM_UNAVAILABLE_MESSAGE
        agent_session_service.append_message(
            session, agent_session=agent_session, role=AgentRole.ASSISTANT, content=reply
        )
        agent_session_service.touch(session, agent_session)
        logger.error("agent.llm_unavailable", session_id=str(agent_session.id))
        return AgentTurnResult(reply=reply, draft_booking_id=None, emergency=False)

    reply = result.final_output if isinstance(result.final_output, str) else str(result.final_output)
    agent_session_service.append_message(
        session,
        agent_session=agent_session,
        role=AgentRole.ASSISTANT,
        content=reply,
        agent_name=result.last_agent.name,
    )
    agent_session_service.touch(session, agent_session)

    return AgentTurnResult(
        reply=reply, draft_booking_id=context.last_draft_booking_id, emergency=False
    )
