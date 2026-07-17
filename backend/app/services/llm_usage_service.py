"""F26 — LLM cost guard. Records per-provider token spend on every agent/
summary call and answers "where are we against the daily budget" for the
4-step degradation ladder in CLAUDE.md's Agent Architecture section:

  1. Gemini 429/error -> retry with backoff             (llm/client.py)
  2. Gemini circuit open -> OpenAI fallback              (llm/client.py)
  3. Daily token budget 80% (across both providers) -> alert
  4. Budget 100% OR both providers down -> agents disabled, manual booking
     flow unaffected

Steps 3-4 are implemented here; callers (agents/runner.py,
services/ai_summary_service.py) check `get_budget_status` before spending
any tokens and record actual usage after a successful call.
"""

from datetime import date as date_type
from enum import StrEnum

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.llm_usage import DailyLLMUsage

logger = get_logger(__name__)

WARNING_THRESHOLD = 0.8


class BudgetStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


def _today() -> date_type:
    return now_utc().date()


def record_usage(session: Session, *, provider: str, requests: int, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
    if total_tokens <= 0 and requests <= 0:
        return

    today = _today()
    row = session.exec(
        select(DailyLLMUsage).where(DailyLLMUsage.usage_date == today, DailyLLMUsage.provider == provider)
    ).first()
    if row is None:
        row = DailyLLMUsage(usage_date=today, provider=provider)

    row.requests += requests
    row.input_tokens += input_tokens
    row.output_tokens += output_tokens
    row.total_tokens += total_tokens
    row.updated_at = now_utc()

    session.add(row)
    session.commit()

    _maybe_alert(session)


def get_today_total_tokens(session: Session) -> int:
    rows = session.exec(select(DailyLLMUsage).where(DailyLLMUsage.usage_date == _today())).all()
    return sum(row.total_tokens for row in rows)


def get_today_tokens_by_provider(session: Session) -> dict[str, int]:
    rows = session.exec(select(DailyLLMUsage).where(DailyLLMUsage.usage_date == _today())).all()
    return {row.provider: row.total_tokens for row in rows}


def get_budget_status(session: Session) -> BudgetStatus:
    budget = get_settings().llm_daily_token_budget
    if budget <= 0:
        return BudgetStatus.OK

    spent = get_today_total_tokens(session)
    ratio = spent / budget
    if ratio >= 1.0:
        return BudgetStatus.EXCEEDED
    if ratio >= WARNING_THRESHOLD:
        return BudgetStatus.WARNING
    return BudgetStatus.OK


def _maybe_alert(session: Session) -> None:
    status = get_budget_status(session)
    spent = get_today_total_tokens(session)
    budget = get_settings().llm_daily_token_budget
    if status is BudgetStatus.EXCEEDED:
        logger.error("llm.budget_exceeded", spent_tokens=spent, budget=budget)
    elif status is BudgetStatus.WARNING:
        logger.warning("llm.budget_warning_80pct", spent_tokens=spent, budget=budget)
