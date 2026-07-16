"""F19 — output guardrail: blocks drug names, dosages, and diagnosis
language from patient-facing agent responses before they render. Heuristic
(regex/keyword), not a trained classifier — there's no ML infra in this
stack; calibrating against a labeled dataset is F21's job. Attached only to
the patient-facing agents (triage/booking/reschedule/faq) — the internal
Summary Agent (F20's AI visit summary) is a doctor-facing clinical drafting
aid and is expected to use clinical language, so it does not get this
guardrail.
"""

import re

from agents import Agent, GuardrailFunctionOutput, OutputGuardrailTripwireTriggered, RunContextWrapper, output_guardrail

from app.agents.context import MedBookAgentContext

SAFE_FALLBACK_MESSAGE = (
    "I can't give medical advice, diagnoses, or medication recommendations — "
    "that needs a doctor to assess in person. I can help you find a doctor "
    "and book an appointment though."
)

_DOSAGE_PATTERN = re.compile(r"\b\d+\s?(mg|ml|mcg|milligrams?|millilitres?|tablets?|capsules?)\b", re.IGNORECASE)

_DIAGNOSIS_PATTERNS = (
    re.compile(r"\byou (have|likely have|probably have|are suffering from)\b", re.IGNORECASE),
    re.compile(r"\bdiagnosis\s*:", re.IGNORECASE),
    re.compile(r"\bthis (is|looks like|sounds like) [a-z\s]*(infection|disease|syndrome|condition)\b", re.IGNORECASE),
    re.compile(r"aap\s?ko\b.*\bhai\b", re.IGNORECASE),
)

# Common OTC/prescription names seen in the Pakistani market — not
# exhaustive, but enough to catch an agent naming a specific medicine
# instead of deferring to a doctor.
_DRUG_NAME_KEYWORDS: tuple[str, ...] = (
    "panadol", "paracetamol", "disprin", "aspirin", "ibuprofen", "brufen",
    "augmentin", "amoxicillin", "azithromycin", "zithromax", "flagyl",
    "metronidazole", "calpol", "ponstan", "voltaren", "diclofenac",
    "omeprazole", "risek", "ciprofloxacin", "ciproxin", "panadol cf",
)


def scan_output(text: str) -> tuple[bool, str | None]:
    if _DOSAGE_PATTERN.search(text):
        return True, "dosage_pattern"
    for pattern in _DIAGNOSIS_PATTERNS:
        if pattern.search(text):
            return True, "diagnosis_language"
    lowered = text.lower()
    for drug in _DRUG_NAME_KEYWORDS:
        if drug in lowered:
            return True, "drug_name"
    return False, None


@output_guardrail
def patient_output_guardrail(
    ctx: RunContextWrapper[MedBookAgentContext], agent: Agent, agent_output: object
) -> GuardrailFunctionOutput:
    text = agent_output if isinstance(agent_output, str) else str(agent_output)
    blocked, reason = scan_output(text)
    return GuardrailFunctionOutput(output_info={"reason": reason}, tripwire_triggered=blocked)


__all__ = [
    "patient_output_guardrail",
    "scan_output",
    "SAFE_FALLBACK_MESSAGE",
    "OutputGuardrailTripwireTriggered",
]
