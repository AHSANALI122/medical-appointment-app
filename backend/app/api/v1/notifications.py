import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.user import User
from app.schemas.notification import NotificationRead, UnreadCountRead
from app.schemas.pagination import Page, PageParams
from app.services import notification_service

router = APIRouter()


@router.get("", response_model=Page[NotificationRead])
def list_notifications(
    unread_only: bool = False,
    params: PageParams = Depends(),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Page[NotificationRead]:
    notifications, total = notification_service.list_notifications(
        session, user_id=user.id, unread_only=unread_only, offset=params.offset, limit=params.page_size
    )
    return Page.create(
        [NotificationRead.model_validate(n, from_attributes=True) for n in notifications],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/unread-count", response_model=UnreadCountRead)
def get_unread_count(
    user: User = Depends(get_current_user), session: Session = Depends(get_session)
) -> UnreadCountRead:
    return UnreadCountRead(unread_count=notification_service.unread_count(session, user_id=user.id))


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> NotificationRead:
    notification = notification_service.mark_read(session, notification_id=notification_id, user_id=user.id)
    return NotificationRead.model_validate(notification, from_attributes=True)


@router.post("/read-all", response_model=UnreadCountRead)
def mark_all_notifications_read(
    user: User = Depends(get_current_user), session: Session = Depends(get_session)
) -> UnreadCountRead:
    notification_service.mark_all_read(session, user_id=user.id)
    return UnreadCountRead(unread_count=0)
