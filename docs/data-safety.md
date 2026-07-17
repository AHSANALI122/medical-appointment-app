# Data Safety & Recovery (F27)

> "Backup jo restore ho ke test na hua ho, wo backup nahi hai."
> A backup that hasn't been restore-tested isn't a backup.

## Point-in-time recovery (Neon)

We use Neon's built-in PITR rather than running our own `pg_dump` cron. It
is continuous (no nightly gap), and restores create a **branch** rather than
overwriting the primary — which is what makes the drill below safe to run
against production data without risking production.

### One-time setup (Neon dashboard — cannot be committed)

1. Project → **Settings → Storage → History retention**.
2. Set retention to **7 days** minimum. (Neon free tier caps at 24h; the
   paid tiers allow 7–30. If we're on free, this is a known gap — write it
   down in the risk register rather than pretending it's covered.)
3. Confirm the retention window is longer than our worst realistic
   detection time. A silent data-corruption bug found on Monday morning
   that started Friday night needs >48h of history to undo.

## Weekly restore drill

Run every Monday. Takes ~10 minutes. **The point is to prove the restore
path works before we need it at 3am**, so run it as written even when
nothing is wrong.

1. Pick a target time ~1 hour ago:
   ```
   TARGET=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
   ```
2. Create a restore branch in the Neon dashboard (**Branches → New branch →
   from a past timestamp**), or via CLI:
   ```
   neonctl branches create --name drill-$(date +%Y%m%d) --parent-timestamp "$TARGET"
   ```
3. Get its connection string and point a throwaway shell at it:
   ```
   DATABASE_URL="<drill-branch-url>" uv run python -c "
   from sqlmodel import Session, select, func, create_engine
   from app.models.booking import Booking
   from app.models.user import User
   import os
   e = create_engine(os.environ['DATABASE_URL'])
   with Session(e) as s:
       print('users:', s.exec(select(func.count()).select_from(User)).one())
       print('bookings:', s.exec(select(func.count()).select_from(Booking)).one())
   "
   ```
4. **Verify, don't glance.** Row counts should be within a plausible delta
   of production for that timestamp. A restore that connects but returns an
   empty schema is a *failed* drill, not a passed one.
5. Confirm migrations are consistent on the branch:
   ```
   DATABASE_URL="<drill-branch-url>" uv run alembic current
   ```
   It must report the same head as production.
6. Delete the drill branch (they consume storage):
   ```
   neonctl branches delete drill-$(date +%Y%m%d)
   ```
7. Record the result — date, target timestamp, row counts, pass/fail — in
   the drill log below. **An unrecorded drill didn't happen.**

### Drill log

| Date | Target timestamp | Users | Bookings | Alembic head matches | Result |
|---|---|---|---|---|---|
| _(first drill pending — run this and fill the row in)_ | | | | | |

## Migration safety

Rules, enforced by review:

1. **Every migration ships a working `downgrade`.** All 9 current migrations
   satisfy this, verified by actually running
   `upgrade head → downgrade base → upgrade head` against a scratch database
   — not by reading the code.

   Do that verification for real when adding a migration. A `downgrade()`
   that merely *exists* is not a working one: `9133db2c73a5` had a
   complete-looking downgrade that dropped every table it created, and the
   chain still failed on the way back up with `type "reminderoffset" already
   exists`. **Postgres ENUM types are separate objects that `op.drop_table()`
   does not remove.** If a migration creates an enum, its downgrade must
   drop it explicitly:

   ```python
   bind = op.get_bind()
   for enum_name in ('reminderoffset', 'reviewmoderationstatus'):
       sa.Enum(name=enum_name).drop(bind, checkfirst=True)
   ```

   Verify with:

   ```bash
   # against a throwaway database, never a real one
   DATABASE_URL="...=/medbook_migrationtest?..." uv run alembic upgrade head
   DATABASE_URL="..." uv run alembic downgrade base
   DATABASE_URL="..." uv run alembic upgrade head   # this is the step that catches it
   ```
2. **Destructive changes are two-phase.** Dropping a column happens across
   two releases:
   - *Release N (deprecate)*: stop reading and writing the column in code;
     leave the column in place.
   - *Release N+1 (remove)*: drop the column, once release N is confirmed
     stable and no rollback to N-1 is plausible.

   The reason is rollback: if release N drops a column and we then roll the
   *code* back to N-1, the old code selects a column that no longer exists
   and every request 500s. Expand-contract keeps old code running against
   new schema, which is exactly what F29's rollback plan depends on.
3. **Autogenerate output is reviewed, not trusted.** `alembic revision
   --autogenerate` in this repo proposes dropping `ix_users_full_name_trgm`
   on every run — a raw-SQL trigram index that isn't reflected in SQLModel
   metadata. Deleting it would silently degrade doctor search. Always read
   the generated file and strip drift that isn't real.

## Account deletion & export

See `app/services/account_deletion_service.py` and
`app/services/data_export_service.py`. Summary of the policy:

| Data | On deletion |
|---|---|
| `User` row | Soft-deleted immediately (`deleted_at` set, login blocked), hard-purged after 30 days |
| Clinical notes, patient notes, medical history, agent chat | **Hard-deleted** at purge |
| Bookings | Anonymised, retained — the doctor's own appointment history must stay intact |
| Reviews | Text anonymised to "Deleted user", **rating preserved** — purging the rating would silently move a doctor's public aggregate |
| Audit logs | **Retained** — they reference IDs and actions, never health content, and they're the record of who touched what |

The 30-day window exists so an accidental or coerced deletion is
recoverable. Purge runs as a sweep job (`app/jobs/purge_sweep.py`), DB-driven
off `deleted_at`, so it survives restarts like every other TTL in this
codebase.
