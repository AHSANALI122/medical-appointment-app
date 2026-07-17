from pydantic import BaseModel


class EndpointLatencyRead(BaseModel):
    endpoint: str
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float


class BookingFunnelRead(BaseModel):
    reached_draft: int
    reached_pending: int
    reached_confirmed: int
    draft_to_pending_rate: float
    pending_to_confirmed_rate: float
    draft_to_confirmed_rate: float


class LLMSpendRead(BaseModel):
    date: str
    total_tokens: int
    budget: int
    used_fraction: float
    status: str
    by_provider: dict[str, int]


class MetricsRead(BaseModel):
    latency: list[EndpointLatencyRead]
    funnel: BookingFunnelRead
    llm_spend: LLMSpendRead
