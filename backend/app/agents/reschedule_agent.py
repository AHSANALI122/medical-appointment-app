from agents import Agent

from app.agents.context import MedBookAgentContext
from app.agents.tools import RESCHEDULE_TOOLS
from app.guardrails.output_scanner import patient_output_guardrail

reschedule_agent: Agent[MedBookAgentContext] = Agent(
    name="Reschedule Agent",
    handoff_description="Helps a patient view, cancel, or reschedule an existing booking.",
    instructions=(
        "You help patients manage existing bookings. Use "
        "get_patient_bookings_tool to find the booking they mean, and "
        "check_cancellation_policy_tool before promising a cancellation or "
        "reschedule is possible — some doctors require more notice than "
        "others. reschedule_booking_tool cancels the old booking and opens "
        "a fresh 10-minute hold at the new time; always tell the patient "
        "they still need to tap Confirm on the new time in the app. Never "
        "reschedule or cancel a booking the patient hasn't clearly "
        "identified and confirmed."
    ),
    tools=RESCHEDULE_TOOLS,
    output_guardrails=[patient_output_guardrail],
)
