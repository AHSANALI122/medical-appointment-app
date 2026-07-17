"""F26 — request latency percentiles per endpoint.

In-process and bounded: each endpoint keeps a fixed-size ring buffer of the
most recent durations, so memory is capped no matter how long the process
runs and percentiles reflect *recent* behaviour rather than an all-time
average that never moves after a bad hour. Same "in-process singleton,
swap the backing store later" shape as core/rate_limit.py — on a
multi-instance deployment each instance reports its own slice, which is
called out here rather than hidden. The external uptime monitor
(docs/observability.md) is what actually pages; this endpoint is for
"which route got slow" triage.

Keyed by route *template* (`/api/v1/doctors/{doctor_id}`), never the raw
path — keying by raw path would mint a new series per doctor id and grow
without bound.
"""

import threading
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.timezone import now_utc

MAX_SAMPLES_PER_ENDPOINT = 1_000


@dataclass(frozen=True)
class EndpointLatency:
    endpoint: str
    count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile. `sorted_values` must be non-empty."""
    rank = max(1, min(len(sorted_values), round(pct / 100 * len(sorted_values))))
    return sorted_values[rank - 1]


class LatencyRegistry:
    def __init__(self) -> None:
        self._samples: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def record(self, endpoint: str, duration_ms: float) -> None:
        with self._lock:
            bucket = self._samples.get(endpoint)
            if bucket is None:
                bucket = deque(maxlen=MAX_SAMPLES_PER_ENDPOINT)
                self._samples[endpoint] = bucket
            bucket.append(duration_ms)

    def snapshot(self) -> list[EndpointLatency]:
        with self._lock:
            raw = {endpoint: list(bucket) for endpoint, bucket in self._samples.items()}

        results = []
        for endpoint, values in raw.items():
            if not values:
                continue
            values.sort()
            results.append(
                EndpointLatency(
                    endpoint=endpoint,
                    count=len(values),
                    p50_ms=round(_percentile(values, 50), 2),
                    p95_ms=round(_percentile(values, 95), 2),
                    p99_ms=round(_percentile(values, 99), 2),
                )
            )
        return sorted(results, key=lambda r: r.p95_ms, reverse=True)

    def reset(self) -> None:
        """Test-only escape hatch — the registry is process-global by design."""
        with self._lock:
            self._samples.clear()


_registry = LatencyRegistry()


def get_latency_registry() -> LatencyRegistry:
    return _registry


def route_template(request: Request) -> str:
    """The full templated path for a request, e.g.
    `/api/v1/doctors/{doctor_id}`.

    Not as simple as reading `route.path`: this FastAPI version nests
    included routers rather than flattening them, so the matched route only
    knows its own leaf (`/{doctor_id}`), and `root_path` stays empty. Using
    the leaf directly would silently merge unrelated endpoints — `/me`
    exists under both /doctors and /bookings, and their latencies would land
    in one meaningless bucket.

    So: take the real path and substitute each matched path param back out.
    A route with no params is already its own template.
    """
    if request.scope.get("route") is None:
        # No match (404). Their raw paths are attacker-controlled and
        # unbounded — exactly the cardinality blowup this module avoids —
        # so they collapse into one series.
        return "unmatched"

    path = request.scope.get("path", "")
    params = request.scope.get("path_params") or {}

    template = path
    for name, value in params.items():
        # count=1: replace only the first occurrence, so an id that happens
        # to also appear elsewhere in the path isn't clobbered twice.
        template = template.replace(str(value), "{" + name + "}", 1)
    return template


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = now_utc()
        response = await call_next(request)
        duration_ms = (now_utc() - started).total_seconds() * 1000

        get_latency_registry().record(
            f"{request.method} {route_template(request)}", duration_ms
        )
        return response
