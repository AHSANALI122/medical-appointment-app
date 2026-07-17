"""F20 — minimal DB-backed feature flags so each smart feature (waitlist,
follow-up, AI summary, family accounts) can be toggled independently by an
admin without a redeploy, per F20's acceptance criterion. A missing row
defaults to enabled — flags are an opt-out switch for something already
built, not an opt-in gate that needs provisioning first.
"""

from collections.abc import Callable

from fastapi import Depends
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.exceptions import ForbiddenError
from app.models.feature_flag import FeatureFlag

WAITLIST = "waitlist"
FOLLOWUP = "followup"
AI_SUMMARY = "ai_summary"
FAMILY_ACCOUNTS = "family_accounts"

# F29 — the admin API lists/validates against this set rather than against
# whatever rows exist, because a key with no row is *enabled* (see
# `is_enabled`): listing only existing rows would show an empty page while
# every feature was silently on, and accepting arbitrary keys would let a
# typo ("watilist") create a row that gates nothing.
KNOWN_FLAGS = (WAITLIST, FOLLOWUP, AI_SUMMARY, FAMILY_ACCOUNTS)


def is_enabled(session: Session, key: str) -> bool:
    flag = session.exec(select(FeatureFlag).where(FeatureFlag.key == key)).first()
    if flag is None:
        return True
    return flag.enabled


def set_enabled(session: Session, *, key: str, enabled: bool) -> FeatureFlag:
    flag = session.exec(select(FeatureFlag).where(FeatureFlag.key == key)).first()
    if flag is None:
        flag = FeatureFlag(key=key, enabled=enabled)
    else:
        flag.enabled = enabled
    session.add(flag)
    session.commit()
    session.refresh(flag)
    return flag


def require_enabled(session: Session, key: str) -> None:
    if not is_enabled(session, key):
        raise ForbiddenError(f"the '{key}' feature is currently disabled")


def require_feature(key: str) -> Callable[[Session], None]:
    """FastAPI dependency factory — `dependencies=[Depends(require_feature(WAITLIST))]`
    on a router/route, same shape as `core.rate_limit.rate_limit()`."""

    def _dependency(session: Session = Depends(get_session)) -> None:
        require_enabled(session, key)

    return _dependency
