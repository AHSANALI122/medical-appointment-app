import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationChannel, NotificationStatus


class NotificationRead(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID | None = None
    channel: NotificationChannel
    status: NotificationStatus
    title: str
    body: str
    read_at: datetime | None = None
    created_at: datetime


class UnreadCountRead(BaseModel):
    unread_count: int


class EmailBounceWebhook(BaseModel):
    """Shape modeled on Resend's bounce/delivery-failure webhook payload:
    https://resend.com/docs/dashboard/webhooks/event-types — trimmed to the
    two fields the fallback logic actually needs."""

    provider_message_id: str
    reason: str = "bounced"
