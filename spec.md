# MedBook — Medical Appointment Booking Platform
## Product Spec v4 (F0–F31) — Final, Post Two Critic Passes + Production Layer

**Stack**
- Frontend: Next.js 15 (App Router, TypeScript), Tailwind CSS, shadcn/ui, Framer Motion
- Backend: FastAPI (Python, `uv`), SQLModel, PostgreSQL (Neon), Alembic
- AI: OpenAI Agents SDK; Gemini free tier (via LiteLLM) primary, OpenAI fallback
- Observability: LangSmith
- Auth: JWT httpOnly cookies
- Deployment: Vercel (frontend) + Railway (backend) + Neon (DB)

---

## ⚠️ Canonical Booking State Machine (single source of truth)

All features (F4, F5, F18) MUST follow this one state machine. No feature may define its own states.

```
draft ──(patient tap ≤10 min)──▶ pending ──(doctor accepts)──▶ confirmed ──▶ completed
  │                                │                              │
  └─(TTL)──▶ expired               ├─(doctor rejects)─▶ rejected  ├──▶ cancelled (by patient OR doctor)
                                   └─(TTL)──▶ expired             └──▶ no_show
```

- `draft`: created by agent OR manual UI. **Fee + location snapshot taken HERE — the moment the patient sees the card.** Holds the slot; `expires_at = now + 10 min` (DB column + sweep job, not in-memory scheduler — survives restarts). UI shows countdown timer.
- `expired`: terminal state for timed-out drafts AND timed-out pendings; slot released (excluded from unique constraint).
- `pending`: patient tapped Confirm. Slot held. **Pending TTL: doctor must accept within 24h OR by T-2h before appointment start, whichever is earlier** — else auto-`expired`, patient notified with alternatives. (A doctor who never opens the app can no longer trap a patient's slot in limbo.)
- `confirmed`: doctor accepted. The **draft-time snapshots** simply become immutable — doctor fee changes between draft and acceptance never affect what the patient agreed to. If doctor edited fee after draft creation, acceptance screen warns doctor they're accepting at the old snapshotted fee.
- `completed`: auto-marked 24h after appointment end unless already `no_show`; doctor may mark earlier. **Correction window: admin can flip `completed` ↔ `no_show` within 7 days** (handles doctor-forgot-then-autocomplete race).
- `no_show`: doctor/admin only, only after start time.
- `cancelled`: `cancelled_by` field records patient vs doctor vs admin. **Doctor-initiated cancellation** allowed anytime with mandatory reason → patient notified + top waitlist candidates + reschedule suggestions.
- **Reschedule = cancel + new booking** (`rescheduled_from_id`), and the new booking goes through the full `draft → pending → confirmed` cycle again (doctor re-accepts). Patient-initiated reschedule obeys the same 2-hour policy window as cancellation. Fee snapshot carries over only if same doctor and new date within 7 days.
- **Booking validity window (all creation paths, server-enforced):** `start_time` must be ≥ 30 min in the future and ≤ 60 days ahead.

**Timezone rule (global):** all timestamps stored UTC; all display and slot generation in `Asia/Karachi`. No client-local-time math on booking-critical paths.

---

### F0 — Project Setup & Architecture
- Monorepo: `/frontend` (Next.js) + `/backend` (FastAPI, uv-managed)
- Env management: `.env.local` / `.env` — never committed; `.env.example` maintained
- Provider-agnostic LLM layer (`llm/client.py`): Gemini + OpenAI behind one interface, swap via env var
- Acceptance: both apps boot cleanly; `/health` returns DB + LLM-provider status

### F1 — User Roles & Auth
- Roles: `patient`, `doctor`, `admin`
- Patients self-register. **Doctors also self-register** but land in `unverified` state (see F23) — they cannot appear in search or receive bookings until admin verifies PMC number. (v1 ambiguity fixed: previously said admin creates doctor accounts, which contradicted F23 self-signup.)
- JWT (httpOnly cookie), bcrypt hashing, refresh-token rotation
- **Public browsing allowed**: doctor search/profiles viewable without login; booking requires patient login
- Acceptance: role guards on frontend middleware + backend dependencies; unverified doctor cannot access doctor dashboard booking features

### F2 — Doctor & Clinic Profiles
- Profile: name, specialization (from fixed taxonomy list — free text banned, needed for reliable triage routing in F17), qualifications, photo (Cloudinary signed upload), bio, consultation fee, clinic location(s)
- Multiple clinics per doctor (address, map embed)
- Acceptance: profile page renders fee + locations; specialization values only from taxonomy table

### F3 — Availability & Slot Management
- Weekly recurring availability + exception dates (leave/holiday)
- Slot duration configurable per doctor (15/30/45/60 min)
- Slots generated dynamically from rules; **conflict prevention via UNIQUE constraint on `(doctor_id, clinic_location_id, start_time_utc)` in bookings table with status in (draft, pending, confirmed)** — concurrent insert loses cleanly. (v1 fix: optimistic-locking-with-version-column was impossible since dynamic slots have no row to version.)
- Doctor leave after bookings exist → all affected bookings auto-flagged, patients notified, reschedule suggested (links to F20)
- Acceptance: pytest concurrency test — 10 parallel booking attempts on same slot, exactly 1 succeeds

### F4 — Appointment Booking Flow (Manual UI)
- Search → slot select → fee + location review → creates `draft` → patient taps Confirm → `pending`
- Framer Motion stepper (Select Doctor → Slot → Review → Confirm)
- **No optimistic UI on confirmation** — button shows loading state until server ACK. (v1 fix: optimistic UI contradicted the double-booking guarantee; a patient could see "confirmed" then lose the race.)
- Acceptance: state transitions atomic; UI never displays a state the server hasn't persisted

### F5 — Booking Lifecycle Management
- Doctor/admin accepts (`pending` → `confirmed`) or rejects
- Patient cancellation policy: allowed until **2 hours before appointment start** (configurable per doctor, floor = 1h); after window, cancel button disabled with reason shown
- Email (Resend) + in-app notification on every state change
- Acceptance: state changes reflect on patient dashboard ≤5s (SSE preferred, polling fallback); policy window enforced server-side, not just UI

### F6 — Appointment Notes
- Patient note at booking (reason/symptoms)
- Doctor clinical notes post-visit, private by default, per-note "share with patient" toggle
- Both encrypted at rest (Fernet/AES via app-level encryption)
- Acceptance: access-control tests — patient cannot read unshared clinical note via API even with valid JWT

### F7 — Fees Snapshot
- Fee shown at profile, re-shown at review step, **snapshotted into booking at `draft` creation** (the number the patient actually saw and agreed to) and immutable from `confirmed` onward. (v2 loophole fixed: snapshotting at `confirmed` meant a doctor could raise the fee between the patient's tap and acceptance — patient agrees to Rs. 1500, gets charged Rs. 2500.)
- Reschedule fee rule: see state machine section
- Payment: cash-at-clinic default; online payment behind stub interface (out of scope v1)
- Acceptance: changing doctor fee never mutates any existing booking's `fee_charged`

### F8 — Location Snapshot
- Address + map + directions link at profile, review step, and confirmation email
- Multi-clinic: explicit location choice at booking; `clinic_location_id` + denormalized address text snapshotted at `confirmed` (address text copied so later clinic edits don't rewrite history)
- Acceptance: editing a clinic address does not change what past bookings display

### F9 — AI Assistant *(superseded by F17)*
- **This feature is fully absorbed into F17's multi-agent architecture.** Retained as a number only for traceability. There is ONE chat system in the app, not two. (v1 fix: F9 and F17 read as two separate assistants.)

### F10 — Search & Discovery
- Filters: specialization (taxonomy), city, fee range, next-available-slot, rating; full-text on name
- Only `verified` doctors appear (F23)
- Acceptance: paginated, indexed, p95 < 500ms on 10k-doctor seed dataset (dataset size now explicit)

### F11 — Reviews & Ratings
- One review per `completed` booking; `no_show` and `cancelled` bookings cannot review
- Review window: up to 30 days after completion
- Admin moderation queue; doctor may reply once per review
- Acceptance: API-level test that non-completed booking review attempt returns 403

### F12 — Reminders & Notifications
- Reminders at T-24h and T-1h (APScheduler; jobs keyed by `booking_id + offset` for idempotency)
- Reminders sent only for `confirmed` bookings; cancelled/rescheduled bookings' pending jobs revoked
- In-app notification center with unread count
- Acceptance: reschedule/cancel test verifies stale reminders never fire

### F13 — Doctor Dashboard
- Today + upcoming schedule, pending acceptances, patient notes + medical history panel, availability editor, leave management
- Acceptance: row-level authorization — doctor A requesting doctor B's booking gets 403 (explicit pytest)

### F14 — Admin Dashboard
- PMC verification queue (F23), booking oversight, review moderation, platform stats
- Acceptance: all admin routes 403 for non-admin JWT

### F15 — Security & Compliance
- Rate limiting (Upstash Redis): auth endpoints, booking endpoints, **and `/chat` agent endpoint (strictest — LLM calls are the most expensive resource)** (v1 gap fixed)
- Pydantic validation everywhere; no raw SQL
- Health data (notes, medical history) encrypted at rest; encryption keys in env/secret manager, key-rotation procedure documented
- CSRF protection on cookie auth; CORS locked to frontend origin
- Audit log table: who read/wrote clinical notes + medical history, when (append-only)
- Acceptance: security pytest suite — SQLi, XSS, CSRF, IDOR (patient A accessing patient B's booking), auth bypass

### F16 — Deployment & CI/CD
- GitHub Actions: frontend lint+typecheck+build, backend ruff+pytest, on every PR
- Auto-deploy on merge to `main` (Vercel + Railway); migrations run via release phase
- Acceptance: red pipeline blocks merge; smoke test hits `/health` post-deploy

---

## Agentic Layer (OpenAI Agents SDK)

### F17 — Multi-Agent Assistant Architecture
- OpenAI Agents SDK; Gemini via LiteLLM primary, OpenAI fallback (F22 circuit breaker)
- **Session persistence**: conversation history stored server-side (per patient session table); agent runs receive prior turns — multi-turn context survives page refresh. (v1 gap: sessions were undefined.)
- Agents & handoffs:
  - **Triage Agent** (entry): Roman Urdu/Urdu/English symptom text → specialization from taxonomy → handoff. Never diagnoses.
  - **Booking Agent**: `search_doctors`, `get_available_slots`, `create_draft_booking` (creates `draft`, NOT pending — naming aligned with state machine)
  - **Reschedule Agent**: `get_patient_bookings`, `check_cancellation_policy`, `reschedule_booking`
  - **FAQ Agent**: answers via **structured DB tools** (`get_doctor_info`, `get_policy_doc`) — RAG only over static help/policy markdown docs, NOT over doctor data. (v1 fix: RAG over structured DB data was the wrong tool; SQL-backed tools are exact, cheaper, and can't hallucinate fees.)
- Agent context carries authenticated `user_id` + **active `patient_profile_id`** server-side (family accounts: user selects which profile — "Ammi ke liye booking" — via UI selector before/during chat; agent tool `set_active_profile` limited to profiles owned by the JWT's user). Agent cannot act on another user's data by prompt manipulation.
- **Chat messages encrypted at rest** — patients type symptoms into chat, making `AgentMessage` health data just like clinical notes (same Fernet/AES layer); retention: 12 months then purge. (v2 gap: notes and history were encrypted but symptom-laden chat wasn't.)
- Acceptance: LangSmith traces show full handoff chain + tool calls per session; cross-patient access attempt via prompt fails in red-team suite

### F18 — HITL Booking Confirmation
- Agent creates `draft` only; frontend confirmation card (fee, time, location) → patient tap → `pending`
- Draft TTL: 10 min auto-expiry releases slot (see state machine); card shows live countdown
- **Abuse guard: max 3 active drafts per patient profile, max 1 per doctor** — otherwise a patient (or a retry loop in chat) could hoard many held slots simultaneously. `create_draft_booking` is idempotent per (profile, doctor, slot).
- Acceptance: zero bookings pass `draft` without explicit tap; expired drafts free their slot (tested); audit log records confirmer + timestamp

### F19 — Safety Guardrails
- **Emergency detection = two layers**: (1) keyword fast-path (chest pain, saans, behosh, bleeding, seene mein dard...) for zero-latency catch, (2) LLM classifier guardrail for phrasing variants keywords miss. Either trips → booking flow halted, 1122 + nearest-ER message shown. (v1 fix: keyword-only was brittle.)
- Output guardrail: blocks drug names, dosages, diagnosis language before rendering
- Prompt-injection defense: user text as data; tool inputs Pydantic-validated; system prompts immutable; patient identity from JWT, never from message content
- Acceptance: red-team pytest suite ≥ 30 adversarial prompts (injection, emergency paraphrases, cross-patient attempts) passes 100%

### F20 — Smart Features (Agent-Powered)
- **Waitlist**: full slot → join waitlist → on cancellation, FIFO notify with 15-min exclusive hold. **Hold mechanism = a system-created `draft` booking for the waitlisted profile** (`hold_expires_at` = 15 min instead of 10) — reuses the existing unique-constraint machinery instead of inventing a parallel locking system; expiry hands hold to next in line. **System-created holds are exempt from the patient's draft limits (F18)** — a waitlist win must never be blocked because the patient happens to have an unrelated draft open with the same doctor; `source` field (`user`/`system_waitlist`) distinguishes them. (v2 gap: hold was declared but its mechanism undefined.)
- **Follow-up**: doctor sets "follow-up in N weeks" at completion → notification with suggested slots. **If N weeks exceeds the 60-day booking horizon, the suggestion notification is deferred until the target date enters the horizon** (scheduled job) — otherwise every "3 mahine baad aana" follow-up would silently fail validation.
- **AI visit summary**: doctor rough notes → structured draft (Gemini) → doctor edits/approves before save (HITL); draft never auto-saves
- **Family accounts**: one `User` → multiple `PatientProfile` records; **bookings reference `patient_profile_id`, not `user_id`** (data model updated below); medical history is per-profile
- Acceptance: feature-flagged independently; waitlist hold expiry tested

### F21 — Agent Observability & Evals
- LangSmith tracing: sessions, handoffs, tool calls, tokens, latency
- LLM-as-judge evals: triage routing accuracy, guardrail catch rate, booking completion rate
- **Golden dataset: minimum 100 labeled triage examples** (Roman Urdu heavy) built from traces + synthetic; judge calibrated to ≥85% human agreement before trusting scores (your established methodology)
- CI: prompt/agent changes trigger eval run; triage accuracy ≥90% AND emergency-detection recall ≥99% gate deployment (recall target added — missing an emergency is the worst failure mode, so it gets a stricter bar than routing accuracy)
- Acceptance: eval report artifact attached to every agent-touching PR

### F22 — Error Handling & Resilience
- **Backend**: global exception handler (no stack leaks), structured errors `{error_code, message, request_id}`, custom exceptions (`SlotUnavailableError`, `BookingConflictError`, `PolicyViolationError`, `LLMProviderError`), request-ID middleware linked to LangSmith traces
- **LLM layer**: exponential backoff on 429 (max 3), Gemini→OpenAI circuit breaker (60s cooldown), 30s agent timeout → graceful message + manual booking flow always remains usable
- **Booking paths**: transactions with rollback; idempotency keys on booking creation; **conflict handling via the F3 unique constraint** (v1 fix: removed impossible version-column locking)
- **Frontend**: route-level error boundaries, retry UI for flaky networks
- **Jobs**: dead-letter queue for failed reminders; alert on repeat failures
- Acceptance: chaos suite — provider kill mid-run, concurrent same-slot bookings, network drop at confirm — zero data corruption

### F23 — Doctor Verification (PMC)
- Doctor self-signup collects PMC registration number → `unverified`
- Admin queue: verify against PMC record → `verified` / `rejected` (with reason)
- Only `verified` doctors searchable/bookable; badge on profile + booking card
- Acceptance: unverified doctor invisible in search API results and cannot receive `draft` bookings (server-enforced)

### F24 — Patient Medical History Profile
- Per **PatientProfile** (family-account aware): allergies, medications, chronic conditions, blood group, surgeries
- Auto-attached read-only to bookings; **visible to a doctor only while they hold a booking with that profile in `pending`/`confirmed`/`completed` state within the last 12 months** (v1 fix: "booked doctor" access window was undefined — now bounded)
- Patient edits anytime; append-only version history
- Encrypted at rest; all reads logged to audit table (F15)
- Acceptance: doctor with only `cancelled`/`rejected` or stale bookings gets 403 on history endpoint

### F25 — SMS Fallback & Multi-Channel Reminders
- Channel priority: in-app → email → SMS
- **SMS triggers: email hard-bounce or delivery failure, OR patient preference set to SMS-first.** (v1 fix: "unopened email" removed — open tracking is unreliable pixel-based guesswork and a false trigger source.)
- Urdu/English templates; delivery status tracked per channel per booking
- Acceptance: delivery report per booking; email failure → SMS within 5 min (tested with mocked bounce webhook)

---

## Data Model v2 (Core Entities)
```
User (role) ─1:N─ PatientProfile (family accounts)
User(doctor) ─1:1─ DoctorProfile (verification_status, specialization_id) ─1:N─ ClinicLocation
DoctorProfile ─1:N─ AvailabilityRule / AvailabilityException
Booking (patient_profile_id, doctor_id, clinic_location_id,
         start_time_utc, status, source[user|system_waitlist],
         fee_charged, address_snapshot, expires_at,
         idempotency_key, rescheduled_from_id, cancelled_by)
         UNIQUE(doctor_id, clinic_location_id, start_time_utc) WHERE status IN (draft,pending,confirmed)
Booking ─1:1─ PatientNote / ClinicalNote (encrypted)
PatientProfile ─1:1─ MedicalHistory (encrypted, versioned)
Booking ─1:1─ Review
AgentSession ─1:N─ AgentMessage (chat persistence, encrypted)
AuditLog (append-only)
SpecializationTaxonomy
Waitlist (slot_key, patient_profile_id, position, hold_expires_at)
FeatureFlag (key, enabled)                      ← F29
ConsentRecord (user_id, type, granted_at)       ← F31
```

## Build Order (Final)
**Milestone 1 — Shippable Core:** F0 → F1 → F2 (+taxonomy) → F3 → F4 (+state machine) → F5 → F7+F8 → F23 → F6 → F24 → F12 → F25 → F10 → F13 → F14 → F22 → F15 → F16
**Milestone 2 — Agentic Layer:** F17 → F18 → F19 → F21 → F20 → F11
**Milestone 3 — Production Hardening:** F26 → F27 → F28 → F29 → F30 → F31
(Day-one rules from CLAUDE.md — structured logging, /api/v1, pagination, reversible migrations, Sentry — apply from F0, not deferred to Milestone 3.)

## Changelog: Critic Fixes Applied (v1 → v2)
1. **Slot-blocking loophole**: agent-created pending bookings could hold slots forever → `draft` state + 10-min TTL added
2. **Contradictory confirmation authority**: F4/F5/F18 each implied a different confirmer → one canonical state machine
3. **Impossible locking mechanism**: version-column optimistic locking on dynamically generated (row-less) slots → replaced with partial UNIQUE constraint
4. **F1 vs F23 contradiction**: admin-creates-doctors vs doctor-self-signup → unified as self-signup + verification gate
5. **Optimistic UI vs atomicity**: instant confirmation display could show a booking that lost the race → removed, server-ACK only
6. **Two chat systems ambiguity**: F9 vs F17 → F9 formally superseded
7. **RAG misuse**: RAG over structured doctor/fee data invites hallucinated fees → structured tools instead, RAG for static docs only
8. **Undefined completion trigger**: nobody was assigned to mark `completed` → auto-complete at +24h, doctor override
9. **Reschedule fee ambiguity**: immutable fee vs reschedule undefined → explicit 7-day/same-doctor carry-over rule
10. **Medical history access window unbounded** → 12-month active-booking window
11. **"Unopened email" SMS trigger unreliable** → bounce/failure + preference triggers only
12. **Keyword-only emergency detection brittle** → dual-layer (keywords + LLM classifier), recall ≥99% deploy gate
13. **Missing chat rate limiting** → added, strictest tier
14. **Family accounts broke data model** → `PatientProfile` entity, bookings re-keyed
15. **Agent session persistence undefined** → AgentSession/AgentMessage tables
16. **Timezone handling absent** → UTC storage + Asia/Karachi display rule
17. **Vague eval dataset** → min 100 examples, judge calibration ≥85% human agreement
18. **Free-text specialization** would break triage routing → fixed taxonomy table

## Changelog: Second Critic Pass (v2 → v3)
1. **Fee bait-and-switch loophole (serious)**: v2 snapshotted fee at `confirmed` — doctor could raise fee between patient's tap and acceptance; patient agrees to Rs. 1500, record locks Rs. 2500. → Snapshot now taken at `draft` creation, i.e., the number the patient actually saw.
2. **Pending-state limbo (serious)**: v2 fixed the draft TTL but left `pending` unbounded — an unresponsive doctor could hold a patient's slot forever with no resolution. → Pending TTL: 24h or T-2h, whichever first, then auto-expire + notify with alternatives.
3. **Unnamed expiry state**: state machine said "auto-release slot" but defined no terminal state for it, leaving the unique-constraint status list ambiguous. → `expired` state added, excluded from constraint.
4. **Doctor-initiated cancellation missing**: only patient cancel + leave flow existed; a doctor cancelling a single confirmed booking had no defined path. → `cancelled_by` field, mandatory reason, waitlist + reschedule triggers.
5. **Reschedule under-specified**: unclear whether reschedule obeyed the 2-hour policy window and whether the doctor re-accepts the new booking. → Both now explicit (yes and yes).
6. **Slot-hoarding abuse**: nothing stopped a patient or a chat retry loop from creating many simultaneous drafts, holding multiple slots. → Max 3 active drafts per profile, 1 per doctor, idempotent tool.
7. **Family accounts broke agent identity**: F17 pinned `patient_id` but bookings are per `patient_profile_id` — whose booking does "kal ka slot le lo" create? → Active-profile selector, `set_active_profile` restricted to JWT-owned profiles.
8. **Chat = unencrypted health data**: symptoms typed into chat weren't covered by the encryption policy that covered notes/history. → AgentMessage encrypted at rest + 12-month retention.
9. **In-memory TTL fragility**: 10-min expiry via scheduler jobs dies on restart, leaving zombie drafts holding slots. → DB `expires_at` column + sweep job.
10. **completed/no_show race**: auto-complete at +24h could beat a forgetful doctor, making no_show unmarkable. → 7-day admin correction window.
11. **Waitlist hold mechanism undefined**: 15-min hold declared with no locking mechanism. → Implemented as system-created draft, reusing the unique constraint.
12. **No booking horizon/lead-time validation**: nothing prevented booking a slot starting in 2 minutes or 2 years. → ≥30 min lead, ≤60 days horizon, server-enforced on all creation paths.

---

## Production-Grade Layer

### F26 — Observability & Monitoring (beyond LangSmith)
- **Structured logging**: JSON logs (structlog), request_id in every line, log levels env-driven; no print statements anywhere
- **Error tracking**: Sentry on both frontend + backend (source maps uploaded in CI)
- **Uptime monitoring**: external ping on `/health` (Better Stack/UptimeRobot free tier), alert on 2 consecutive failures
- **Metrics**: p50/p95/p99 latency per endpoint, booking funnel counters (draft→pending→confirmed conversion), LLM token spend per day
- **LLM cost guard + degradation ladder** (resolves overlap with F22 fallback — the order is now explicit):
  1. Gemini 429/error → retry with backoff (F22)
  2. Gemini circuit open → OpenAI fallback (F22)
  3. Daily token budget 80% (across both providers) → alert
  4. Budget 100% OR both providers down → agents disabled, chat shows "assistant temporarily unavailable," **manual booking flow unaffected** (site never dies because free tier exhausted)
- Acceptance: kill backend → alert within 5 min; every 5xx visible in Sentry with request_id traceable to logs + LangSmith trace

### F27 — Data Safety & Recovery
- Neon PITR (point-in-time recovery) enabled; weekly restore drill documented (backup jo restore ho ke test na hua ho, wo backup nahi hai)
- Alembic migration safety: every migration reversible (`downgrade` implemented); destructive migrations (column drops) two-phase (deprecate → remove next release)
- **Account deletion (patient right)**: soft-delete + 30-day purge job; bookings anonymized (doctor's history intact), **reviews anonymized to "Deleted user" (rating preserved — doctor's aggregate must not silently change)**, notes/history/chat hard-deleted; audit log rows retained (they reference IDs, not health content)
- Data export: patient can download their data (JSON) — bookings, notes shared with them, history
- Acceptance: restore drill doc in repo; delete → purge verified by test; export endpoint returns complete data

### F28 — Performance & Scale Readiness
- DB: connection pooling (Neon pgbouncer URL), indexes audited per query (EXPLAIN in review for every list endpoint), N+1 prevention (selectinload)
- Caching: doctor profiles + search results in Redis (60s TTL, invalidate on profile update); taxonomy cached in-process
- Pagination mandatory on every list endpoint (cursor-based for bookings)
- Frontend: next/image everywhere, route-level code splitting, Lighthouse ≥90 performance/accessibility on doctor profile + search pages
- Load test: k6 script — 200 concurrent users browsing + 50 booking simultaneously, p95 < 800ms, zero booking corruptions
- Acceptance: k6 report committed; Lighthouse CI check in pipeline

### F29 — API & Release Discipline
- API versioned under `/api/v1`; OpenAPI docs auto-generated, publicly readable at `/docs` (auth-gated in prod)
- Graceful shutdown: in-flight requests drained on deploy (uvicorn lifespan), sweep jobs idempotent across restarts
- Rollback plan: Railway/Vercel instant rollback to previous deploy; migrations decoupled from deploy (expand-contract pattern) so old code runs on new schema
- Feature flags: simple DB-backed flags table (F20 features, new agents) — ship dark, enable gradually
- Seed script: 20 doctors, taxonomy, demo patients — one command bootstraps a demo environment
- Acceptance: deploy → rollback → deploy cycle tested without downtime or data loss

### F30 — E2E Testing & Release Gates
- Playwright e2e suite: signup → search → book → confirm → doctor accepts → reminder fires (mocked clock) → complete → review
- Critical-path e2e runs on every PR; full suite nightly
- Staging environment (separate Neon branch + Railway service) — every release hits staging first, smoke suite must pass before prod promote
- Acceptance: green e2e required for prod deploy; staging→prod promotion documented as single command/action

### F31 — Legal & Trust Surface
- Privacy policy + Terms pages (health data handling, retention windows, what AI assistant does/doesn't do)
- Explicit consent checkbox at signup for health-data processing; consent timestamp stored
- Medical disclaimer on every AI assistant surface (persistent, not dismissible)
- Cookie/session notice
- Acceptance: no booking or chat possible without recorded consent

## Changelog: Final Consistency Audit (v3 → v4)
1. **F22 vs F26 conflict**: F22 said "Gemini fails → OpenAI fallback," F26 said "budget 100% → manual mode" — two rules claiming the same failure with different outcomes. → Explicit 4-step degradation ladder (retry → fallback → alert → agents-off/manual-intact).
2. **Waitlist hold vs draft limits**: system-created hold drafts could be blocked by the "1 draft per doctor" abuse guard, making a patient lose their waitlist win to their own unrelated draft. → System holds exempt via `source` field.
3. **Deletion vs reviews**: purging a patient left their reviews orphaned/undefined and could silently distort doctor ratings. → Anonymize review text, preserve rating; audit log retained (IDs only, no health content).
4. **Follow-up vs 60-day horizon**: "follow-up in 12 weeks" would fail the ≤60-day booking validation every time. → Deferred suggestion job until target date enters horizon.
5. **Stale metadata**: title still said "v2 (F0–F25)"; build order omitted F26–F31. → Updated; build order restructured into 3 milestones (shippable core → agents → production).
6. **Data model drift**: `expires_at`, `cancelled_by`, `source`, FeatureFlag, ConsentRecord existed in feature text but not in the data model. → Added.
7. **CLAUDE.md env vars incomplete**: SENTRY_DSN, LLM_DAILY_TOKEN_BUDGET, SMS gateway key referenced by features but absent from the env template. → Added.
