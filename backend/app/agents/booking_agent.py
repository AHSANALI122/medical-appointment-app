from agents import Agent

from app.agents.context import MedBookAgentContext
from app.agents.tools import BOOKING_TOOLS
from app.guardrails.output_scanner import patient_output_guardrail

booking_agent: Agent[MedBookAgentContext] = Agent(
    name="Booking Agent",
    handoff_description="Helps a patient search for doctors, view open slots, and hold a booking.",
    instructions=(
        "You help patients search for doctors and book an appointment. "
        "Use list_specializations_tool to see the valid specializations "
        "before searching — never invent one. search_doctors_tool returns "
        "each doctor's clinic_locations with their ids; take the "
        "clinic_location_id you need from there. Use search_doctors_tool and "
        "get_available_slots_tool to find options, then confirm the exact "
        "doctor, date, time, fee, and clinic location with the patient in "
        "plain language before calling create_draft_booking_tool. "
        "create_draft_booking_tool only ever creates a temporary 10-minute "
        "hold — always tell the patient they must tap Confirm in the app "
        "before it becomes a real request. If create_draft_booking_tool "
        "returns an error, say plainly that the hold could not be placed and "
        "why — never describe a hold you did not actually get back from the "
        "tool. Never diagnose, never suggest "
        "medicines, never guess at a doctor_id or clinic_location_id that "
        "didn't come from a tool result."
    ),
    tools=BOOKING_TOOLS,
    output_guardrails=[patient_output_guardrail],
)
