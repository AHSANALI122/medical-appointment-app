"""F26 degradation ladder step 4 — once the daily token budget is exhausted,
`run_agent_turn` must never call the LLM at all (agents disabled) while
still persisting the exchange, and the manual booking flow is untouched.
"""

import pytest

from app.agents.runner import AGENTS_DISABLED_MESSAGE, run_agent_turn
from app.core.config import get_settings
from app.services import llm_usage_service


@pytest.mark.usefixtures("agent_session")
async def test_budget_exceeded_short_circuits_before_any_llm_call(
    session, patient_user, agent_session, fake_llm
):
    budget = get_settings().llm_daily_token_budget
    llm_usage_service.record_usage(
        session, provider="gemini", requests=1, input_tokens=0, output_tokens=0, total_tokens=budget
    )

    # No scripted responses at all — if the runner tried to call the LLM,
    # FakeModel would raise "ran out of scripted responses".
    fake_llm([])

    result = await run_agent_turn(
        session, user=patient_user, agent_session=agent_session, user_message="mujhe doctor chahiye"
    )

    assert result.reply == AGENTS_DISABLED_MESSAGE
    assert result.emergency is False
    assert result.draft_booking_id is None


async def test_under_budget_still_calls_llm(session, patient_user, agent_session, fake_llm):
    from tests.agents.fake_model import clean_turn

    fake_llm(clean_turn("Sure, what symptoms are you having?"))

    result = await run_agent_turn(
        session, user=patient_user, agent_session=agent_session, user_message="hi"
    )

    assert result.reply == "Sure, what symptoms are you having?"
