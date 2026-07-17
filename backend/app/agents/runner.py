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
from app.services import agent_session_service, llm_usage_service
from app.services.llm_usage_service import BudgetStatus

logger = get_logger(__name__)

LLM_UNAVAILABLE_MESSAGE = (
    "I'm having trouble connecting right now. Please try again in a moment, "
    "or use the search page to book directly — that always works even when "
    "I'm down."
)

AGENTS_DISABLED_MESSAGE = (
    "The assistant is temporarily unavailable right now. Please use the "
    "search page to find and book a doctor directly — booking always works "
    "even when the assistant is off."
)


def _record_llm_usage(session: Session, router, result) -> None:
    provider = router.last_provider_used
    if provider is None:
        return
    usage = result.context_wrapper.usage
    llm_usage_service.record_usage(
        session,
        provider=provider.value,
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
    )


@dataclass
class AgentTurnResult:
    reply: str
    draft_booking_id: uuid.UUID | None
    emergency: bool


async def _call_llm(session: Session, context: MedBookAgentContext, input_items: list[dict]):
    router = get_resilient_router()

    async def run_fn(model):
        context.resolved_model = model
        return await Runner.run(
            triage_agent, input=input_items, context=context, run_config=RunConfig(model=model)
        )

    result = await router.run(run_fn)
    _record_llm_usage(session, router, result)
    return result


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

    # F26 degradation ladder step 4: budget exhausted -> no LLM call at all,
    # manual booking (search page) stays fully functional.
    if llm_usage_service.get_budget_status(session) is BudgetStatus.EXCEEDED:
        agent_session_service.append_message(
            session, agent_session=agent_session, role=AgentRole.USER, content=user_message
        )
        agent_session_service.append_message(
            session,
            agent_session=agent_session,
            role=AgentRole.ASSISTANT,
            content=AGENTS_DISABLED_MESSAGE,
            agent_name="budget_guard",
        )
        agent_session_service.touch(session, agent_session)
        logger.warning("agent.budget_exceeded_disabled", session_id=str(agent_session.id))
        return AgentTurnResult(reply=AGENTS_DISABLED_MESSAGE, draft_booking_id=None, emergency=False)

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
        result = await _call_llm(session, context, input_items)
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
