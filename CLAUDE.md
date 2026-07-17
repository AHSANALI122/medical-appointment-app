# CLAUDE.md — MedBook (Medical Appointment Booking Platform)

## What This Project Is
Multi-role medical appointment booking platform for Pakistan: patients book doctors, confirm time/fee/location, with an agentic AI assistant (OpenAI Agents SDK) for triage → booking. Full spec in `spec.md` (F0–F25, v3 post-critic). **Read spec.md before implementing any feature. The Canonical Booking State Machine section at the top of spec.md overrides anything else — no feature may invent its own booking states.**

## Stack (fixed — do not substitute)
- **Frontend**: Next.js 15 App Router, TypeScript strict, Tailwind CSS, shadcn/ui, Framer Motion
- **Backend**: FastAPI, Python 3.12+, `uv` for all package management (`uv add`, `uv run` — never pip)
- **DB**: PostgreSQL (Neon), SQLModel, Alembic migrations
- **Agents**: OpenAI Agents SDK; Gemini free tier via LiteLLM (`gemini/gemini-2.5-flash`) primary, OpenAI fallback via env-driven provider layer
- **Observability**: LangSmith (tracing + evals)
- **Auth**: JWT in httpOnly cookies, bcrypt
- **Infra**: Cloudinary (signed uploads), Resend (email), Upstash Redis (rate limits), APScheduler (jobs) + DB-backed expiry sweeps

## Repo Layout
```
/frontend          Next.js app
/backend
  /app
    /api           routers (auth, doctors, bookings, chat, admin)
    /models        SQLModel entities
    /agents        Agents SDK: triage, booking, reschedule, faq, summary
    /llm           provider-agnostic client (Gemini/OpenAI)
    /services      booking state machine, slots, notifications
    /guardrails    emergency detection, output scanner, injection defense
    /jobs          reminders, TTL sweeps, waitlist
  /tests           pytest (unit, concurrency, red-team, chaos)
spec.md            THE source of truth
CLAUDE.md          this file
```

## Non-Negotiable Rules
1. **State machine is law.** Statuses: `draft, pending, confirmed, completed, cancelled, rejected, expired, no_show`. All transitions via a single `BookingStateMachine` service — never raw status updates scattered in routers.
2. **Slot conflicts = DB unique constraint**, partial index on `(doctor_id, clinic_location_id, start_time_utc) WHERE status IN ('draft','pending','confirmed')`. No version columns, no advisory locks, no app-level "check then insert".
3. **Snapshots at draft creation**: `fee_charged` + `address_snapshot` written when draft is created (what patient saw), immutable from `confirmed`.
4. **TTLs are DB columns + sweep jobs** (`expires_at`), never in-memory-only scheduler state. Draft = 10 min, pending = min(24h, T-2h), waitlist hold = 15 min.
5. **Agents never finalize.** `create_draft_booking` creates `draft` only. Patient tap → `pending`. Doctor accepts → `confirmed`. Max 3 active drafts/profile, 1/doctor, idempotent per (profile, doctor, slot).
6. **All times UTC in DB, Asia/Karachi for display/slot generation.** Booking window: start ≥ 30 min future, ≤ 60 days ahead.
7. **Encrypted at rest (Fernet)**: clinical notes, patient notes, medical history, agent chat messages. All reads of medical history → append-only audit log.
8. **Identity from JWT, never from message content.** Agent context: `user_id` + active `patient_profile_id` (family accounts); `set_active_profile` restricted to JWT-owned profiles.
9. **No raw SQL. Pydantic validation on every input, including agent tool args.**
10. **Errors**: global exception handler, structured `{error_code, message, request_id}`, custom exceptions (`SlotUnavailableError`, `BookingConflictError`, `PolicyViolationError`, `LLMProviderError`). Never leak stack traces.

## Agent Architecture (F17–F19)
- Entry = Triage Agent → handoffs to Booking / Reschedule / FAQ. Summary Agent is internal (doctor dashboard only).
- Triage NEVER diagnoses or names medicines. Specializations come from the taxonomy table only.
- **Emergency guardrail (two layers)**: keyword fast-path (chest pain, seene mein dard, saans, behosh, bleeding...) + LLM classifier. Either trips → halt flow, show 1122 message. Emergency recall target ≥99%.
- Output guardrail scans responses for drug names/dosages/diagnosis language before rendering.
- FAQ Agent uses structured DB tools for doctor/fee data (exact answers), RAG only over static policy/help markdown.
- LLM resilience: exponential backoff on 429 (max 3), Gemini→OpenAI circuit breaker (60s cooldown), 30s run timeout with graceful fallback message. Manual booking flow must always work even if agents are down.

## Language & UX Notes
- Patients write in Roman Urdu / Urdu / English — agents must handle all three. Test triage with Roman Urdu inputs ("pait mein dard", "dant mein takleef").
- Draft confirmation card shows live 10-min countdown.
- No optimistic UI on booking confirmation — server ACK before showing success.

## Testing Requirements (per feature, before moving on)
- Unit tests for state machine transitions (every legal + illegal transition)
- Concurrency test: 10 parallel bookings on one slot → exactly 1 succeeds
- Red-team suite: ≥30 adversarial prompts (injection, emergency paraphrases, cross-profile access) — 100% pass
- Chaos: LLM provider killed mid-run, network drop at confirm → zero data corruption
- Mock all LLM calls in unit tests (established pattern from prior projects); live-LLM tests behind a marker

## Build Order (from spec.md)
F0 → F1 → F2 (+taxonomy) → F3 → F4 (+state machine) → F5 → F7+F8 → F23 → F6 → F24 → F12 → F25 → F10 → F13 → F14 → F22 → F15 → F17 → F18 → F19 → F21 → F20 → F11 → F16 → **F26–F31 (production layer)**

Production rules that apply from DAY ONE (not bolted on at the end):
- structlog JSON logging with request_id — never print()
- `/api/v1` prefix on all routes from the first router
- Pagination on every list endpoint from its first version
- Every Alembic migration ships with a working `downgrade`
- Sentry initialized in F0 skeleton
- All list queries reviewed with EXPLAIN; selectinload against N+1
- LLM token spend counter from the first agent call (daily budget guard, F26)

Work feature-by-feature. Each feature: implement → tests green → acceptance criteria from spec.md verified → then next. Do not start agents (F17+) until the manual booking flow (F0–F5) is solid — agents build on those services.

## Env Vars (maintain .env.example)
```
DATABASE_URL, JWT_SECRET, ENCRYPTION_KEY,
GEMINI_API_KEY, OPENAI_API_KEY, LLM_PRIMARY=gemini, LLM_FALLBACK=openai,
LLM_DAILY_TOKEN_BUDGET,
LANGSMITH_API_KEY, LANGSMITH_PROJECT=medbook,
SENTRY_DSN (frontend + backend),
CLOUDINARY_URL, RESEND_API_KEY, UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN,
SMS_GATEWAY_KEY (stub-able in dev),
FRONTEND_ORIGIN
```

Frontend env lives in `frontend/.env.local` (see `frontend/.env.example`):
`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_ENVIRONMENT`,
plus build-time-only `SENTRY_ORG` / `SENTRY_PROJECT` / `SENTRY_AUTH_TOKEN`.
Sentry's browser DSN **must** be `NEXT_PUBLIC_`-prefixed — Next.js won't
expose an unprefixed var to client code.

## Commands
```bash
# backend
cd backend && uv sync && uv run uvicorn app.main:app --reload
uv run pytest                      # all tests
uv run pytest -m "not live_llm"    # CI-safe
uv run alembic upgrade head
uv run python scripts/seed_demo.py # F29: 20 doctors + patients + admin (refuses in prod)

# frontend
cd frontend && npm i && npm run dev
npm run lint && npm run typecheck
npm run e2e:critical               # F30 critical-path e2e (needs backend + seed)
npm run e2e                        # full e2e suite

# load test (F28) — needs a seeded target, never production
cd backend && k6 run loadtest/booking_load_test.js
```

**Tests share one remote Neon database** (`medbook_test`). Never run two
pytest sessions at once — the session-scoped `test_engine` fixture drops
tables on exit and will yank them out from under a concurrent run, producing
a wall of fake `ObjectDeletedError`s. If a run is killed before its teardown
and you've since changed a model, reset the schema (`create_all` only creates
missing *tables*, it never adds columns to existing ones):

```bash
uv run python -c "
import psycopg; from app.core.config import get_settings
b = get_settings().database_url.replace('postgresql+psycopg://','postgresql://')
with psycopg.connect(b.rsplit('/',1)[0]+'/medbook_test', autocommit=True) as c:
    c.execute('DROP SCHEMA public CASCADE'); c.execute('CREATE SCHEMA public')"
```

## Production Layer Docs (F26–F30)
- `docs/observability.md` — logging, Sentry, uptime monitor setup, `/metrics`, LLM degradation ladder
- `docs/data-safety.md` — Neon PITR, weekly restore drill, migration safety, deletion/export policy
- `docs/releases.md` — feature flags, expand-contract, deploy/rollback, staging promotion, test gates
