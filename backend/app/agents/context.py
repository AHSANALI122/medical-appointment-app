"""Agent run context (CLAUDE.md rule 8): identity travels through this
object, never through LLM-supplied tool arguments. Every tool in
`app/agents/tools.py` reads `ctx.context.user_id` /
`ctx.context.active_patient_profile_id` — nothing else is a trustworthy
source of "who is this."
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlmodel import Session

if TYPE_CHECKING:
    from agents.models.interface import Model


@dataclass
class MedBookAgentContext:
    session: Session
    user_id: uuid.UUID
    agent_session_id: uuid.UUID
    active_patient_profile_id: uuid.UUID | None = None

    # Set by create_draft_booking_tool / reschedule_booking_tool when they run,
    # so the turn's caller (runner.run_agent_turn) can surface the created
    # draft to the chat response (F18's HITL confirmation card) without
    # having to parse the SDK's raw tool-call output items.
    last_draft_booking_id: uuid.UUID | None = None

    # The Model instance the resilient router already resolved for this turn
    # (runner.py sets this before calling Runner.run) — reused by the
    # emergency classifier guardrail so it goes through the same
    # primary/fallback provider, not a hardcoded default.
    resolved_model: "Model | None" = None
