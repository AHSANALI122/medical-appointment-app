"""F27 — purges soft-deleted accounts once their 30-day grace period has
elapsed.

Same shape as the other sweeps (CLAUDE.md rule 4): the deadline lives in a
DB column (`users.purge_after`), so a restart can never lose track of an
account that was due, and the job is idempotent — `purge_account` no-ops on
an already-purged row, so a re-run after a crash mid-sweep is safe.

Each account is committed independently: one account failing to purge must
not roll back or block the others.
"""

from sqlmodel import Session

from app.core.logging import get_logger
from app.services import account_deletion_service

logger = get_logger(__name__)


def sweep_purgeable_accounts(session: Session) -> int:
    due = account_deletion_service.list_accounts_due_for_purge(session)

    purged_count = 0
    for user in due:
        try:
            account_deletion_service.purge_account(session, user=user)
            purged_count += 1
        except Exception as exc:  # noqa: BLE001 — one bad row must not stall the queue
            session.rollback()
            logger.error("purge_sweep.account_failed", user_id=str(user.id), error=str(exc))

    return purged_count
