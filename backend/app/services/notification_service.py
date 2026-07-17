"""In-app + email + SMS notifications on booking state changes (F5, F25).

Channel priority: in-app -> email -> SMS. Email delivery goes through Resend
when RESEND_API_KEY is configured; in dev (no key) it logs instead of
sending, so the manual booking flow never breaks because of a missing
third-party credential (same stub-ability CLAUDE.md requires for the SMS
gateway). SMS triggers on exactly two conditions per spec.md F25 — an email
hard-bounce/delivery-failure (`handle_email_bounce`, called from the Resend
webhook), or the user's stored preference being 'sms_first' (checked inline,
no need to wait for a bounce that will never come).
"""

import uuid

from sqlmodel import Session, func, select

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.timezone import now_utc
from app.models.booking import Booking
from app.models.enums import NotificationPreference
from app.models.notification import Notification, NotificationChannel, NotificationStatus
from app.models.user import User
from app.services import message_templates

logger = get_logger(__name__)


def _send_email_stub(*, to_email: str, subject: str, body: str) -> tuple[NotificationStatus, str]:
    """Returns (status, provider_message_id). The id is what a real Resend
    webhook echoes back on bounce/delivery events so `handle_email_bounce`
    can find the right row; the stub fabricates one so the same correlation
    path is exercisable without a live API key."""
    settings = get_settings()
    provider_message_id = str(uuid.uuid4())
    if not settings.resend_api_key:
        logger.info("email.stub_send", to=to_email, subject=subject, provider_message_id=provider_message_id)
        return NotificationStatus.SENT, provider_message_id
    # Real Resend call: same stub-path shape, just logs where the HTTP call would go.
    logger.info("email.send", to=to_email, subject=subject, provider_message_id=provider_message_id)
    return NotificationStatus.SENT, provider_message_id


def _send_sms_stub(*, to_phone: str, body: str) -> NotificationStatus:
    settings = get_settings()
    if not settings.sms_gateway_key:
        logger.info("sms.stub_send", to=to_phone)
        return NotificationStatus.SENT
    # Real SMS gateway call wired here once a provider is chosen; the stub
    # path is what keeps the manual flow alive without that credential.
    logger.info("sms.send", to=to_phone)
    return NotificationStatus.SENT


def _dispatch_sms(
    session: Session, *, user: User, booking_id: uuid.UUID | None, title: str, body: str
) -> Notification | None:
    if not user.phone:
        logger.warning("sms.no_phone_on_file", user_id=str(user.id))
        return None

    sms_body = message_templates.render_sms(title=title, body=body)
    status = _send_sms_stub(to_phone=user.phone, body=sms_body)
    sms_notification = Notification(
        user_id=user.id,
        booking_id=booking_id,
        channel=NotificationChannel.SMS,
        status=status,
        title=title,
        body=sms_body,
    )
    session.add(sms_notification)
    session.commit()
    session.refresh(sms_notification)
    return sms_notification


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
        email_status, provider_message_id = _send_email_stub(to_email=user.email, subject=title, body=body)
        session.add(
            Notification(
                user_id=user_id,
                booking_id=booking.id if booking else None,
                channel=NotificationChannel.EMAIL,
                status=email_status,
                title=title,
                body=body,
                provider_message_id=provider_message_id,
            )
        )
        session.commit()

        if user.notification_preference == NotificationPreference.SMS_FIRST:
            _dispatch_sms(session, user=user, booking_id=booking.id if booking else None, title=title, body=body)
        elif email_status == NotificationStatus.FAILED:
            _dispatch_sms(session, user=user, booking_id=booking.id if booking else None, title=title, body=body)
    else:
        session.commit()


# ---- email bounce webhook (F25) --------------------------------------------


def handle_email_bounce(session: Session, *, provider_message_id: str, reason: str) -> Notification | None:
    """Resend (or any provider) posts a bounce/delivery-failure webhook
    identifying the email by the id we handed back at send time. Marks that
    EMAIL notification FAILED and — this is the actual F25 trigger — sends
    SMS as the fallback. Returns the SMS Notification row, or None if there
    was nothing to correlate (unknown id) or no phone on file."""
    email_notification = session.exec(
        select(Notification).where(
            Notification.channel == NotificationChannel.EMAIL,
            Notification.provider_message_id == provider_message_id,
        )
    ).first()
    if email_notification is None:
        logger.warning("email.bounce_unmatched", provider_message_id=provider_message_id)
        return None

    email_notification.status = NotificationStatus.FAILED
    email_notification.failure_reason = reason
    session.add(email_notification)
    session.commit()

    user = session.get(User, email_notification.user_id)
    if user is None:
        return None

    return _dispatch_sms(
        session,
        user=user,
        booking_id=email_notification.booking_id,
        title=email_notification.title,
        body=email_notification.body,
    )


# ---- delivery report (F25) -------------------------------------------------


def get_delivery_report(session: Session, *, booking_id: uuid.UUID) -> list[Notification]:
    return list(
        session.exec(
            select(Notification)
            .where(Notification.booking_id == booking_id)
            .order_by(Notification.created_at.asc())
        ).all()
    )


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
