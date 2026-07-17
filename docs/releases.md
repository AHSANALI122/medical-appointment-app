# API & Release Discipline (F29) + Release Gates (F30)

## API surface

- **Everything lives under `/api/v1`** (`app/api/v1/__init__.py`). `/health`
  is the deliberate exception — it's infrastructure, not API, and the uptime
  monitor shouldn't care about our versioning.
- **OpenAPI docs**: public at `/docs` in dev; in production the built-in
  routes are disabled and re-served behind `require_admin`, including
  `/openapi.json`. Hiding the UI while leaving the schema open would be
  pointless — the schema enumerates every route we have.

## Feature flags — shipping dark

DB-backed (`feature_flags` table), toggled without a redeploy:

```
GET /api/v1/admin/feature-flags            # effective state of every known flag
PUT /api/v1/admin/feature-flags/{key}      # {"enabled": false}
```

Known keys live in `feature_flag_service.KNOWN_FLAGS`. **A missing row reads
as enabled** — flags are an opt-*out* kill switch for something already
built, not an opt-in gate that needs provisioning before a feature works.
Two consequences worth knowing before you rely on them:

- To ship genuinely dark, insert the flag row disabled *in the same release*
  that adds the feature, then enable it when ready. Adding the code without
  the row means it's live on deploy.
- The admin API validates against `KNOWN_FLAGS`, so a typo'd key is a 404
  rather than a silently-created row that gates nothing.

## Deploy → rollback → deploy

The rollback story rests on **expand-contract migrations**, not on reversing
them. Rolling a migration back on a live database is how you lose data;
rolling *code* back is safe if the schema still supports the old code.

Which is why the rule in `docs/data-safety.md` is non-negotiable: a
destructive change (column drop/rename) ships across two releases. Release N
stops using the column; release N+1 removes it. At any moment, the previous
release's code runs against the current schema.

### Releasing

1. Merge to `main` → CI runs (`ci.yml`: lint, backend tests, evals, frontend
   build; `e2e.yml`: critical-path Playwright).
2. Migrations run as a release step, **before** the new code serves traffic.
   Because migrations are additive (expand-contract), the currently-running
   old code is unaffected by them.
3. New code rolls out. Uvicorn's lifespan drains in-flight requests on the
   old instance; the APScheduler sweeps are abandoned mid-tick on purpose —
   every one is idempotent and driven off a DB deadline column, so the next
   tick after restart picks up exactly where it left off. See `app/main.py`.

### Rolling back

**Code rollback (the normal case, ~30s):**

- Railway: Deployments → pick the previous deployment → *Redeploy*.
- Vercel: Deployments → previous → *Promote to Production*.

Do **not** roll migrations back as part of this. Expand-contract means the
old code runs fine against the new schema. `alembic downgrade` on production
is a data-loss operation reserved for a migration that is itself the bug,
and only after the drill in `docs/data-safety.md` has proven the restore path.

**Data rollback (rare, serious):** use Neon PITR — restore to a branch,
verify, then repoint. Never `downgrade` a live database to undo bad data.

### Acceptance: deploy → rollback → deploy, no downtime or data loss

Rehearse on staging before trusting it in prod:

1. Note the current deployment id and `alembic current`.
2. Deploy a trivial change. Confirm `/health` is 200 throughout (poll it
   every second during the deploy — that's what proves "no downtime", not
   the platform's green checkmark).
3. Roll back to the previous deployment. Confirm `/health` 200 and that a
   booking created *before* the rollback still reads correctly — that's the
   "no data loss" half, and the part expand-contract earns you.
4. Deploy forward again. Confirm the same booking is still intact.

## Staging

Staging is a separate Neon **branch** (not a separate project — a branch
gives production-shaped data without copying secrets around) plus its own
Railway service and Vercel preview environment.

| | Production | Staging |
|---|---|---|
| DB | Neon `main` branch | Neon `staging` branch |
| Backend | Railway prod service | Railway staging service |
| Frontend | Vercel production | Vercel preview |
| `ENVIRONMENT` | `production` | `staging` |
| Demo seed | never (`seed_demo.py` refuses) | yes |

### Staging → prod promotion (single action)

Every release hits staging first, and the smoke suite must pass before
promotion:

```bash
# 1. staging is deployed from main automatically on merge.
# 2. smoke-test staging:
E2E_BASE_URL=https://staging.medbook.pk \
NEXT_PUBLIC_API_URL=https://staging-api.medbook.pk \
  npm --prefix frontend run e2e:critical

# 3. promote (the single action):
vercel promote <staging-deployment-url> --scope <team>   # frontend
railway redeploy --service medbook-api --environment production  # backend
```

If step 2 is red, stop. A staging environment nobody gates on is just a
second place to be surprised.

## Test gates

| Gate | Runs | Blocks |
|---|---|---|
| `ruff check` | every PR | merge |
| `pytest -m "not live_llm"` | every PR | merge |
| Emergency-recall eval (deterministic) | every PR | merge |
| Live triage eval | PRs with a provider key | merge (when it runs) |
| Playwright `--project=critical` | every PR | merge |
| Playwright full suite | nightly 02:00 UTC | next-morning triage |
| k6 load test | manual / pre-release | release sign-off |

Blocking merge on red is a GitHub branch-protection setting (Settings →
Branches → Require status checks), not something a workflow file can
enforce on itself. Turn it on for `main` once these workflows have each run
at least once.
