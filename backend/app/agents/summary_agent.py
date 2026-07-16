"""F20 — AI visit summary. Internal only (doctor dashboard, never patient
chat) — not part of the triage handoff graph, invoked directly from a
doctor-only endpoint. Produces a DRAFT only; the doctor must review, edit,
and save it themselves through the existing clinical-note endpoint (HITL —
this agent never writes to the database). Unlike the patient-facing agents,
this one is expected to use clinical language, so it does NOT get the F19
output guardrail.
"""

from pydantic import BaseModel

from agents import Agent


class VisitSummaryDraft(BaseModel):
    chief_complaint: str
    assessment: str
    plan: str


summary_agent: Agent[None] = Agent(
    name="Visit Summary Agent",
    instructions=(
        "You are an internal drafting aid used only by doctors, never shown "
        "directly to a patient. Given a doctor's rough, possibly shorthand "
        "notes from a patient visit, produce a clean, structured draft "
        "clinical note with a chief complaint, assessment, and plan. "
        "Standard clinical language is expected and appropriate here. This "
        "is a DRAFT ONLY for the doctor to review and edit — you are not "
        "saving anything or communicating with the patient."
    ),
    output_type=VisitSummaryDraft,
)
