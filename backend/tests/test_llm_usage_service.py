"""F26 — LLM cost guard: daily token spend tracking and the 80%/100%
degradation-ladder thresholds (services/llm_usage_service.py)."""

from app.core.config import get_settings
from app.services import llm_usage_service
from app.services.llm_usage_service import BudgetStatus


class TestRecordUsage:
    def test_upserts_same_day_same_provider(self, session):
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=100, output_tokens=50, total_tokens=150
        )
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=10, output_tokens=5, total_tokens=15
        )

        assert llm_usage_service.get_today_total_tokens(session) == 165

    def test_separate_providers_both_count_toward_daily_total(self, session):
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=100, output_tokens=0, total_tokens=100
        )
        llm_usage_service.record_usage(
            session, provider="openai", requests=1, input_tokens=200, output_tokens=0, total_tokens=200
        )

        assert llm_usage_service.get_today_total_tokens(session) == 300

    def test_zero_usage_is_a_noop(self, session):
        llm_usage_service.record_usage(
            session, provider="gemini", requests=0, input_tokens=0, output_tokens=0, total_tokens=0
        )
        assert llm_usage_service.get_today_total_tokens(session) == 0


class TestBudgetStatus:
    def test_ok_below_80_percent(self, session):
        budget = get_settings().llm_daily_token_budget
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=0, output_tokens=0,
            total_tokens=int(budget * 0.5),
        )
        assert llm_usage_service.get_budget_status(session) == BudgetStatus.OK

    def test_warning_at_80_percent(self, session):
        budget = get_settings().llm_daily_token_budget
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=0, output_tokens=0,
            total_tokens=int(budget * 0.85),
        )
        assert llm_usage_service.get_budget_status(session) == BudgetStatus.WARNING

    def test_exceeded_at_100_percent(self, session):
        budget = get_settings().llm_daily_token_budget
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=0, output_tokens=0,
            total_tokens=budget,
        )
        assert llm_usage_service.get_budget_status(session) == BudgetStatus.EXCEEDED

    def test_exceeded_sums_across_providers(self, session):
        budget = get_settings().llm_daily_token_budget
        llm_usage_service.record_usage(
            session, provider="gemini", requests=1, input_tokens=0, output_tokens=0,
            total_tokens=int(budget * 0.6),
        )
        llm_usage_service.record_usage(
            session, provider="openai", requests=1, input_tokens=0, output_tokens=0,
            total_tokens=int(budget * 0.6),
        )
        assert llm_usage_service.get_budget_status(session) == BudgetStatus.EXCEEDED
