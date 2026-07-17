# Observability & Monitoring (F26)

What's in the code vs. what a human has to click. Everything in "In the
repo" runs automatically; everything in "External setup" needs an account
on a third-party dashboard and is documented here because it cannot be
committed.

## In the repo

| Concern | Where | Notes |
|---|---|---|
| Structured JSON logs | `app/core/logging.py` | structlog, `request_id` bound per request via `RequestIDMiddleware`. Log level from `LOG_LEVEL`. No `print()` anywhere. |
| Request IDs | `app/core/request_context.py` | Accepts an inbound `X-Request-ID` or mints one; echoed on the response and included in every error body. |
| Backend error tracking | `app/main.py` | Sentry initialised at import when `SENTRY_DSN` is set, `traces_sample_rate=0.1`. |
| Frontend error tracking | `frontend/sentry.*.config.ts` | `@sentry/nextjs`; source maps uploaded in CI (see below). |
| Latency percentiles | `app/core/metrics.py` | p50/p95/p99 per route **template**, bounded ring buffer (1000 samples/endpoint). Exposed at `GET /api/v1/metrics` (admin only). |
| Booking funnel | `app/services/funnel_service.py` | draft → pending → confirmed conversion, read from `pending_at`/`confirmed_at` timestamps. |
| LLM token spend | `app/services/llm_usage_service.py` | Per-provider daily totals in `daily_llm_usage`, DB-backed so it survives restarts. |
| Health check | `GET /health` | Public, unauthenticated. Reports DB reachability + LLM provider config. |

### Reading the metrics endpoint

```bash
curl -s https://<api-host>/api/v1/metrics -H "Cookie: access_token=<admin-jwt>" | jq
```

Latency is **per-instance and in-process**: each running instance reports
only the requests it served, and the numbers reset on deploy. That is a
deliberate tradeoff (no metrics backend to run for v1) and it means this
endpoint answers *"which route is slow right now"*, not *"what was our p95
last Tuesday"*. If we ever need historical latency, that's a Prometheus/
OTel exporter, not a bigger ring buffer.

## External setup (manual, one-time)

### Uptime monitoring — required by F26 acceptance

Neither Better Stack nor UptimeRobot can be configured from this repo.
Set up on whichever free tier we're using:

1. Create an HTTP monitor against `https://<api-host>/health`.
2. **Interval: 1 minute.**
3. **Alert after 2 consecutive failures** — this is the F26 requirement
   ("alert within 5 min"); at a 1-min interval, 2 failures alerts in ~2-3
   min, comfortably inside the window. Do not alert on a single failure:
   Neon's serverless Postgres can cold-start slowly enough to blow one
   check, and a monitor that cries wolf gets muted, which is worse than no
   monitor.
4. Expected status: `200`. `/health` returns **503** when the DB is
   unreachable (even though the process is up), so a plain status-code
   check is sufficient — no response-body keyword matching needed.
   LLM provider availability deliberately does *not* affect the status
   code; agents being down must not page anyone, because manual booking is
   unaffected.
5. Notification channel: whatever the team actually reads (email at
   minimum).

### Sentry source maps

`SENTRY_DSN` (backend) and `NEXT_PUBLIC_SENTRY_DSN` (frontend) must be set
in the deploy environment. For source-map upload in CI, `SENTRY_AUTH_TOKEN`
and `SENTRY_ORG`/`SENTRY_PROJECT` must be present as repo secrets — the
frontend build step uploads maps automatically when they are, and silently
skips upload when they aren't (so forks and local builds don't fail).

Acceptance check: trigger a 5xx, confirm the event appears in Sentry with a
`request_id` tag, and confirm grepping that same `request_id` in the
platform logs returns the matching structured lines.

## LLM degradation ladder (F26, resolves the F22 overlap)

The order is explicit, and each step is implemented in exactly one place:

| Step | Trigger | Behaviour | Code |
|---|---|---|---|
| 1 | Gemini 429 / timeout / connection error | Retry, exponential backoff, max 3 attempts | `llm/client.py` `_retrying_primary` |
| 2 | Gemini circuit open (after failure, 60s cooldown) | Fall back to OpenAI, single attempt | `llm/client.py` `ResilientModelRouter.run` |
| 3 | Daily token budget ≥80% (both providers summed) | `llm.budget_warning_80pct` at WARNING → Sentry/log alert | `services/llm_usage_service.py` |
| 4 | Budget ≥100% **or** both providers down | Agents disabled — chat replies "temporarily unavailable"; **manual booking flow unaffected** | `agents/runner.py` |

Step 4 is the one that matters most: the site must never die because a free
tier ran out. `run_agent_turn` checks the budget *before* spending a call
and returns `AGENTS_DISABLED_MESSAGE`; nothing on the search → draft →
confirm → accept path touches the LLM client at all. `tests/test_chaos.py`
asserts exactly this ("manual booking flow unaffected while LLM is down").

To raise the budget: set `LLM_DAILY_TOKEN_BUDGET` (tokens/day, summed
across providers). Setting it to `0` disables the guard entirely — the
counters still record, nothing is ever blocked.
