# MedBook — Medical Appointment Booking Platform

A multi-role medical appointment booking platform for Pakistan. Patients search
verified doctors, see real fees and clinic locations upfront, and confirm
appointments a doctor actually accepts — with an agentic AI assistant (OpenAI
Agents SDK) that handles triage → booking in Roman Urdu, Urdu, or English.

> The authoritative product spec is [`spec.md`](spec.md) (features F0–F31). The
> **Canonical Booking State Machine** at the top of that file is the single
> source of truth for booking states and overrides everything else.
> Engineering conventions live in [`CLAUDE.md`](CLAUDE.md).

---

## Features

- **Doctor search** by specialization, city, and fee, with the next available
  slot shown per doctor.
- **Booking state machine** — a single service governs every transition
  (`draft → pending → confirmed → completed`, plus `cancelled`, `rejected`,
  `expired`, `no_show`). Slot conflicts are prevented by a DB unique constraint,
  not app-level checks.
- **Fee & address snapshots** taken at draft time so patients are charged
  exactly what they saw.
- **Agentic AI assistant** — a Triage agent hands off to Booking / Reschedule /
  FAQ agents. Two-layer emergency detection (keyword fast-path + LLM classifier)
  halts the flow and shows the 1122 emergency message. Agents create drafts
  only; they never finalize a booking.
- **Multi-role dashboards** — patient, doctor, and admin.
- **Family accounts**, medical history (encrypted at rest), reminders, waitlist,
  and reviews.
- **Production layer** — structured JSON logging, Sentry, `/health` and
  `/metrics`, LLM budget guard + provider failover, PITR/backup drills, feature
  flags, and end-to-end tests.

## Tech Stack

| Layer         | Technology |
|---------------|------------|
| Frontend      | Next.js 16 (App Router), TypeScript, Tailwind CSS, shadcn/ui, Framer Motion |
| Backend       | FastAPI, Python 3.12+, `uv` for packaging |
| Database      | PostgreSQL (Neon), SQLModel, Alembic |
| AI / Agents   | OpenAI Agents SDK; Gemini (`gemini-2.5-flash`) via LiteLLM primary, OpenAI fallback |
| Observability | LangSmith (tracing + evals), Sentry, structlog |
| Auth          | JWT in httpOnly cookies, bcrypt |
| Infra         | Cloudinary, Resend, Upstash Redis, APScheduler |

## Repository Layout

```
/frontend          Next.js app (App Router)
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
/docs              observability, data-safety, release runbooks
spec.md            product spec — source of truth
CLAUDE.md          engineering conventions
```

---

## Getting Started

### Prerequisites

- **Node.js** 20+
- **Python** 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- A **PostgreSQL** database (Neon works well)

### 1. Configure environment

Backend — copy `.env.example` to `.env` and fill in at least `DATABASE_URL`,
`JWT_SECRET`, and `ENCRYPTION_KEY` (LLM keys are optional; the manual booking
flow works without them):

```bash
cp .env.example .env
```

Frontend — copy `frontend/.env.example` to `frontend/.env.local`:

```bash
cp frontend/.env.example frontend/.env.local   # sets NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. Backend

```bash
cd backend
uv sync
uv run alembic upgrade head        # apply migrations
uv run python scripts/seed_demo.py # demo data: 20 doctors, patients, 1 admin (refuses in prod)
uv run uvicorn app.main:app --reload
```

Backend runs at **http://localhost:8000**. It serves JSON only — there is no web
page at the root beyond a small index. Useful URLs:

- `http://localhost:8000/docs` — Swagger UI (dev only)
- `http://localhost:8000/health` — health check (DB + LLM status)
- `http://localhost:8000/api/v1/...` — all API routes

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** — this is the app you interact with.

### Demo accounts

After running the seed script, all demo accounts use the password `demo1234`:

| Role    | Email |
|---------|-------|
| Admin   | `admin@demo.medbook.pk` |
| Patient | `asad@demo.medbook.pk`, `hira@demo.medbook.pk`, `bilal@demo.medbook.pk` |
| Doctor  | `doctor1@demo.medbook.pk` … `doctor20@demo.medbook.pk` |

Dashboards live under `/dashboard/<role>`: `/dashboard/patient`,
`/dashboard/doctor`, `/dashboard/admin`.

---

## Testing

```bash
# backend
cd backend
uv run pytest                   # all tests
uv run pytest -m "not live_llm" # CI-safe (LLM calls mocked)

# frontend
cd frontend
npm run lint
npm run typecheck
npm run e2e:critical            # critical-path e2e (needs backend + seed)
npm run e2e                     # full e2e suite
```

> **Tests share one remote Neon test database** (`medbook_test`). Never run two
> pytest sessions at once — see [`CLAUDE.md`](CLAUDE.md) for the schema-reset
> command if a run is interrupted.

## Deployment

- **Frontend** → Vercel
- **Backend** → Railway (or any container host)
- **Database** → Neon (Postgres with PITR)

Operational runbooks are in [`docs/`](docs): [`observability.md`](docs/observability.md),
[`data-safety.md`](docs/data-safety.md), and [`releases.md`](docs/releases.md).

## Key Conventions

- **State machine is law** — all booking transitions go through one
  `BookingStateMachine` service.
- **All times UTC** in the DB; Asia/Karachi for display and slot generation.
- **Encrypted at rest** (Fernet): clinical notes, patient notes, medical
  history, and agent chat messages. Medical-history reads are audit-logged.
- **Identity comes from the JWT**, never from message content.
- **`/api/v1` prefix** on all routes; pagination on every list endpoint.

See [`CLAUDE.md`](CLAUDE.md) for the full list.
