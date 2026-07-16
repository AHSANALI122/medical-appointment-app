from agents import Agent

from app.agents.context import MedBookAgentContext
from app.agents.tools import FAQ_TOOLS
from app.guardrails.output_scanner import patient_output_guardrail

faq_agent: Agent[MedBookAgentContext] = Agent(
    name="FAQ Agent",
    handoff_description="Answers questions about a specific doctor's fee/location, or MedBook's policies.",
    instructions=(
        "You answer factual questions. For a specific doctor's fee, "
        "location, or verification status, always use get_doctor_info_tool "
        "— never state a fee or address from memory, it may be stale. For "
        "general questions about how booking, cancellation, or emergencies "
        "work, use get_policy_doc_tool. If neither tool has an answer, say "
        "so plainly rather than guessing. Never diagnose or suggest "
        "medicines."
    ),
    tools=FAQ_TOOLS,
    output_guardrails=[patient_output_guardrail],
)
