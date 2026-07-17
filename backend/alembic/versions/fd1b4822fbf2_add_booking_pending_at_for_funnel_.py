"""add booking pending_at for funnel metrics

Revision ID: fd1b4822fbf2
Revises: 758d895c43c0
Create Date: 2026-07-17 14:37:19.634127

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'fd1b4822fbf2'
down_revision: Union[str, Sequence[str], None] = '758d895c43c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('bookings', sa.Column('pending_at', sa.DateTime(timezone=True), nullable=True))

    # Backfill for rows that predate the column. Every status below is only
    # reachable *through* pending per the canonical state machine, so their
    # pending_at is known to be non-null; confirmed_at is the tightest
    # bound we have, falling back to updated_at where it's null.
    #
    # Deliberately NOT backfilled: 'draft' (never reached pending) and
    # 'expired' (ambiguous — could have expired as a draft OR as a pending
    # request, and nothing in the row distinguishes them). Historical
    # expired-at-pending bookings are therefore undercounted in the F26
    # funnel; from this migration forward the stamp is exact.
    op.execute(
        """
        UPDATE bookings
        SET pending_at = COALESCE(confirmed_at, updated_at)
        WHERE status IN ('pending', 'confirmed', 'completed', 'no_show', 'rejected', 'cancelled')
        """
    )

    # NOTE: autogenerate also proposed dropping 'ix_users_full_name_trgm' —
    # a raw-SQL trigram search index not tracked in SQLModel metadata, not
    # real drift. Left untouched.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('bookings', 'pending_at')
