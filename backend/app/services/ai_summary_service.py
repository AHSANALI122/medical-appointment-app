"""F20 — AI visit summary. Doctor-only, internal Summary Agent (F17), HITL:
this returns a draft only and never writes to the database — the doctor
edits and saves it themselves through the existing clinical-note endpoint
(`PUT /bookings/{id}/clinical-note`), which is untouched by this module.
"""

import uuid

from agents import RunConfig, Runner
from sqlmodel import Session

from app.agents.summary_agent import VisitSummaryDraft, summary_agent
from app.core.exceptions import LLMProviderError, PolicyViolationError
from app.llm.client import get_resilient_router
from app.models.doctor import DoctorProfile
from app.services import booking_service, llm_usage_service
from app.services.llm_usage_service import BudgetStatus


async def generate_visit_summary_draft(
    session: Session, *, booking_id: uuid.UUID, doctor: DoctorProfile, rough_notes: str
) -> VisitSummaryDraft:
    # Ownership check only — this doesn't touch the booking or clinical note
    # rows at all, it just proves the doctor is allowed to write about this
    # patient before spending an LLM call.
    booking_service.get_doctor_booking_or_403(session, booking_id=booking_id, doctor=doctor)

    if not rough_notes.strip():
        raise PolicyViolationError("rough notes cannot be empty")

    # F26 degradation ladder step 4 — same budget guard as chat; the doctor
    # can still write the clinical note by hand via the existing endpoint.
    if llm_usage_service.get_budget_status(session) is BudgetStatus.EXCEEDED:
        raise LLMProviderError("daily LLM budget exhausted — write the note manually for now")

    router = get_resilient_router()

    async def run_fn(model):
        return await Runner.run(summary_agent, input=rough_notes, run_config=RunConfig(model=model))

    result = await router.run(run_fn)
    usage = result.context_wrapper.usage
    if router.last_provider_used is not None:
        llm_usage_service.record_usage(
            session,
            provider=router.last_provider_used.value,
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )
    return result.final_output
