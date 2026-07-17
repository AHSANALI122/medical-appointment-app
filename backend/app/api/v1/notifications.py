import uuid

from fastapi import APIRouter, Depends, Header
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.models.booking import Booking
from app.models.doctor import DoctorProfile
from app.models.enums import UserRole
from app.models.user import PatientProfile, User
from app.schemas.notification import EmailBounceWebhook, NotificationRead, UnreadCountRead
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


# ---- delivery report (F25) -------------------------------------------------


@router.get("/booking/{booking_id}/delivery-report", response_model=list[NotificationRead])
def get_delivery_report(
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[NotificationRead]:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFoundError("booking not found")

    if user.role == UserRole.PATIENT:
        owner = session.exec(
            select(PatientProfile).where(
                PatientProfile.id == booking.patient_profile_id, PatientProfile.user_id == user.id
            )
        ).first()
        if owner is None:
            raise ForbiddenError("you do not have access to this booking's delivery report")
    elif user.role == UserRole.DOCTOR:
        doctor = session.exec(select(DoctorProfile).where(DoctorProfile.user_id == user.id)).first()
        if doctor is None or booking.doctor_id != doctor.id:
            raise ForbiddenError("you do not have access to this booking's delivery report")
    elif user.role != UserRole.ADMIN:
        raise ForbiddenError("you do not have access to this booking's delivery report")

    report = notification_service.get_delivery_report(session, booking_id=booking_id)
    return [NotificationRead.model_validate(n, from_attributes=True) for n in report]


# ---- email bounce webhook (F25) --------------------------------------------


@router.post("/webhooks/email-bounce", response_model=NotificationRead | None)
def email_bounce_webhook(
    body: EmailBounceWebhook,
    session: Session = Depends(get_session),
    x_webhook_secret: str | None = Header(default=None),
) -> NotificationRead | None:
    """Provider-agnostic bounce/delivery-failure webhook (modeled on Resend).
    Verified with a shared secret when RESEND_WEBHOOK_SECRET is configured;
    unauthenticated in dev/CI so the stub email path stays exercisable
    without provisioning a real webhook secret, mirroring every other
    stub-able credential in this module."""
    settings = get_settings()
    if settings.resend_webhook_secret and x_webhook_secret != settings.resend_webhook_secret:
        raise UnauthorizedError("invalid webhook secret")

    sms_notification = notification_service.handle_email_bounce(
        session, provider_message_id=body.provider_message_id, reason=body.reason
    )
    return NotificationRead.model_validate(sms_notification, from_attributes=True) if sms_notification else None
