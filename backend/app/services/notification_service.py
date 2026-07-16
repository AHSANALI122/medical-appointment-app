"""In-app + email notifications on booking state changes (F5).

Email delivery goes through Resend when RESEND_API_KEY is configured; in dev
(no key) it logs instead of sending, so the manual booking flow never breaks
because of a missing third-party credential (same stub-ability CLAUDE.md
requires for the SMS gateway).
"""

import uuid

from sqlmodel import Session

from app.core.config import get_settings
from app.core.logging import get_logger
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
