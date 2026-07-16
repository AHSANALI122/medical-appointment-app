"""F19 — emergency detection, two layers per spec.md:

1. Keyword fast-path (`keyword_emergency_check`) — zero-latency, checked
   directly in `runner.run_agent_turn` before any LLM call is made at all,
   AND re-checked inside the guardrail below as defense in depth.
2. LLM classifier (`emergency_input_guardrail`) — catches phrasing variants
   the keyword list misses. Fails open (treats classifier errors as "not an
   emergency") since the keyword layer is the actual safety net; a broken
   classifier call must never crash the whole turn.

Either layer tripping halts the run — `runner.run_agent_turn` catches
`InputGuardrailTripwireTriggered` and returns the 1122 + nearest-ER message
instead of continuing the booking/triage flow.
"""

from pydantic import BaseModel

from agents import Agent, GuardrailFunctionOutput, RunConfig, Runner, RunContextWrapper, input_guardrail
from agents.items import TResponseInputItem

from app.agents.context import MedBookAgentContext

EMERGENCY_MESSAGE = (
    "This sounds like it could be a medical emergency. Please call 1122 "
    "(Pakistan's emergency ambulance service) or go to the nearest hospital "
    "emergency room right away. MedBook can help with booking a follow-up "
    "appointment once the emergency has been addressed."
)

# English / Roman Urdu / Urdu script — deliberately broad, false positives
# here just mean an extra "are you okay, please call 1122" turn, which is a
# far cheaper mistake than missing a real emergency (spec.md's ≥99% recall
# target treats a missed emergency as the worst failure mode).
EMERGENCY_KEYWORDS: tuple[str, ...] = (
    # English
    "chest pain", "can't breathe", "cant breathe", "cannot breathe",
    "difficulty breathing", "shortness of breath", "not breathing",
    "unconscious", "unresponsive", "passed out", "severe bleeding",
    "heavy bleeding", "heart attack", "stroke", "seizure", "convulsion",
    "suicidal", "kill myself", "overdose", "choking",
    # Roman Urdu
    "seene mein dard", "seenay mein dard", "seny mein dard",
    "saans nahi", "saans lene mein", "saans rukh", "saans band",
    "behosh", "be hosh", "khoon beh raha", "zyada khoon", "dil ka dora",
    "dora para", "marne wala", "khudkushi",
    # Urdu script
    "سینے میں درد", "سانس نہیں", "سانس لینے میں", "بے ہوش",
    "خون بہہ رہا", "دل کا دورہ", "خودکشی",
)


def keyword_emergency_check(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in EMERGENCY_KEYWORDS)


def _extract_user_text(input_value: str | list[TResponseInputItem]) -> str:
    """Extracts only the CURRENT turn's user text — deliberately not the
    whole conversation history. `input_value` is the full history + new
    message (runner.run_agent_turn passes prior turns for multi-turn
    context), but scanning all of it here would mean an emergency phrase
    from three turns ago keeps tripping the guardrail on every later,
    unrelated message for the rest of the session. Matches the keyword
    fast-path's turn-scoped behavior in runner.py."""
    if isinstance(input_value, str):
        return input_value

    last_user_content = None
    for item in input_value:
        if isinstance(item, dict) and item.get("role") == "user":
            last_user_content = item.get("content")

    if isinstance(last_user_content, str):
        return last_user_content
    if isinstance(last_user_content, list):
        parts = [
            chunk["text"]
            for chunk in last_user_content
            if isinstance(chunk, dict) and isinstance(chunk.get("text"), str)
        ]
        return "\n".join(parts)
    return ""


class EmergencyClassification(BaseModel):
    is_emergency: bool


_classifier_agent = Agent(
    name="EmergencyClassifier",
    instructions=(
        "You classify a single patient message as a medical emergency or not. "
        "An emergency is anything suggesting an immediate, life-threatening "
        "condition (severe chest pain, can't breathe, unconscious, heavy "
        "bleeding, stroke symptoms, suicidal intent). Routine symptoms "
        "(mild fever, a cough, a headache, wanting to book a checkup) are "
        "NOT emergencies. The message may be in English, Urdu, or Roman "
        "Urdu. Only output the structured classification — never a "
        "diagnosis or advice."
    ),
    output_type=EmergencyClassification,
)


@input_guardrail(run_in_parallel=False)
async def emergency_input_guardrail(
    ctx: RunContextWrapper[MedBookAgentContext],
    agent: Agent,
    agent_input: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:
    text = _extract_user_text(agent_input)

    if keyword_emergency_check(text):
        return GuardrailFunctionOutput(
            output_info={"layer": "keyword", "matched": True}, tripwire_triggered=True
        )

    context = ctx.context
    if context.resolved_model is None or not text.strip():
        return GuardrailFunctionOutput(output_info={"layer": "classifier", "skipped": True}, tripwire_triggered=False)

    try:
        result = await Runner.run(
            _classifier_agent, input=text, run_config=RunConfig(model=context.resolved_model)
        )
        classification = result.final_output
        is_emergency = bool(classification.is_emergency) if classification is not None else False
    except Exception:  # noqa: BLE001 — classifier failure must not crash the turn; keyword layer is the net
        is_emergency = False

    return GuardrailFunctionOutput(
        output_info={"layer": "classifier", "is_emergency": is_emergency}, tripwire_triggered=is_emergency
    )
