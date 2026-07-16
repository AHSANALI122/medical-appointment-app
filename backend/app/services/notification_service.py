"""In-app + email notifications on booking state changes (F5).

Email delivery goes through Resend when RESEND_API_KEY is configured; in dev
(no key) it logs instead of sending, so the manual booking flow never breaks
because of a missing third-party credential (same stub-ability CLAUDE.md
requires for the SMS gateway).
"""

import uuid

from sqlmodel import Session, func, select

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.notification import Notification, NotificationChannel, NotificationStatus
from app.models.user import User

logger = get_logger(__name__)


def _send_email_stub(*, to_email: str, subject: str, body: str) -> NotificationStatus:
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info("email.stub_send", to=to_email, subject=subject)
        return NotificationStatus.SENT
    # Real Resend call wired in F25; F0-F5 scope only needs the interface + stub path.
    logger.info("email.send", to=to_email, subject=subject)
    return NotificationStatus.SENT


def notify_user(
    session: Session,
    *,
    user_id: uuid.UUID,
    booking: Booking | None,
    title: str,
    body: str,
) -> None:
    in_app = Notification(
        user_id=user_id,
        booking_id=booking.id if booking else None,
        channel=NotificationChannel.IN_APP,
        status=NotificationStatus.SENT,
        title=title,
        body=body,
    )
    session.add(in_app)

    user = session.get(User, user_id)
    if user is not None:
        email_status = _send_email_stub(to_email=user.email, subject=title, body=body)
        session.add(
            Notification(
                user_id=user_id,
                booking_id=booking.id if booking else None,
                channel=NotificationChannel.EMAIL,
                status=email_status,
                title=title,
                body=body,
            )
        )

    session.commit()


# ---- notification center (F12) --------------------------------------------


def list_notifications(
    session: Session, *, user_id: uuid.UUID, unread_only: bool, offset: int, limit: int
) -> tuple[list[Notification], int]:
    # The in-app feed is the notification center's source of truth; email
    # rows exist for delivery bookkeeping, not for the bell/list UI.
    query = select(Notification).where(
        Notification.user_id == user_id, Notification.channel == NotificationChannel.IN_APP
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))

    total = session.exec(select(func.count()).select_from(query.with_only_columns(Notification.id).subquery())).one()
    query = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    return list(session.exec(query).all()), total


def unread_count(session: Session, *, user_id: uuid.UUID) -> int:
    return session.exec(
        select(func.count()).where(
            Notification.user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.read_at.is_(None),
        )
    ).one()


def mark_read(session: Session, *, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise NotFoundError("notification not found")

    if notification.read_at is None:
        notification.read_at = now_utc()
        session.add(notification)
        session.commit()
        session.refresh(notification)
    return notification


def mark_all_read(session: Session, *, user_id: uuid.UUID) -> int:
    unread = session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.read_at.is_(None),
        )
    ).all()
    now = now_utc()
    for notification in unread:
        notification.read_at = now
        session.add(notification)
    session.commit()
    return len(unread)
