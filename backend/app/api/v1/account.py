"""F27 — the patient's own data rights: export and deletion.

Everything here resolves the subject from the JWT (`require_patient`) and
never from a path/body parameter — there is deliberately no
"delete/export user X" shape to get wrong (CLAUDE.md rule 8).
"""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.api.deps import require_patient
from app.core.cookies import clear_auth_cookies
from app.core.db import get_session
from app.models.user import User
from app.schemas.account import AccountDeletionRead
from app.services import account_deletion_service, data_export_service

router = APIRouter()


@router.get("/export")
def export_my_data(
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Complete JSON export. Served as a file download rather than a plain
    body so "download my data" is one click in the browser."""
    payload = data_export_service.build_export(session, user=user)
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="medbook-export.json"'},
    )


@router.post("/delete", response_model=AccountDeletionRead)
def request_account_deletion(
    response: Response,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> AccountDeletionRead:
    updated = account_deletion_service.request_deletion(session, user=user)

    # The account is deactivated as of this call, so leaving auth cookies in
    # the browser would just produce confusing 401s on the next click.
    clear_auth_cookies(response)

    return AccountDeletionRead(
        deleted_at=updated.deleted_at,
        purge_after=updated.purge_after,
        message=(
            "Your account is deactivated and you have been signed out. Your data "
            f"will be permanently deleted on {updated.purge_after:%d %B %Y}. "
            "Contact support before that date if you want it restored."
        ),
    )
