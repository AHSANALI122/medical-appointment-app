"""F26 — operational metrics surface: latency percentiles per endpoint,
booking funnel conversion, and today's LLM token spend against budget.

Admin-gated: latency shape and conversion rates are business intelligence,
and the funnel leaks booking volume — neither belongs on a public endpoint.
`/health` stays public for the external uptime monitor (docs/observability.md).
"""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.db import get_session
from app.core.metrics import get_latency_registry
from app.core.timezone import now_utc
from app.schemas.metrics import (
    BookingFunnelRead,
    EndpointLatencyRead,
    LLMSpendRead,
    MetricsRead,
)
from app.services import funnel_service, llm_usage_service

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=MetricsRead)
def get_metrics(session: Session = Depends(get_session)) -> MetricsRead:
    latency = [
        EndpointLatencyRead(
            endpoint=row.endpoint,
            count=row.count,
            p50_ms=row.p50_ms,
            p95_ms=row.p95_ms,
            p99_ms=row.p99_ms,
        )
        for row in get_latency_registry().snapshot()
    ]

    funnel = funnel_service.get_booking_funnel(session)
    budget = get_settings().llm_daily_token_budget
    spent = llm_usage_service.get_today_total_tokens(session)

    return MetricsRead(
        latency=latency,
        funnel=BookingFunnelRead(
            reached_draft=funnel.reached_draft,
            reached_pending=funnel.reached_pending,
            reached_confirmed=funnel.reached_confirmed,
            draft_to_pending_rate=funnel.draft_to_pending_rate,
            pending_to_confirmed_rate=funnel.pending_to_confirmed_rate,
            draft_to_confirmed_rate=funnel.draft_to_confirmed_rate,
        ),
        llm_spend=LLMSpendRead(
            date=now_utc().date().isoformat(),
            total_tokens=spent,
            budget=budget,
            used_fraction=round(spent / budget, 4) if budget > 0 else 0.0,
            status=llm_usage_service.get_budget_status(session).value,
            by_provider=llm_usage_service.get_today_tokens_by_provider(session),
        ),
    )
