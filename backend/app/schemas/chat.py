import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AgentRole
from app.schemas.booking import BookingRead


class ChatSessionRead(BaseModel):
    id: uuid.UUID
    active_patient_profile_id: uuid.UUID | None = None
    created_at: datetime
    last_activity_at: datetime


class ChatMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageRead(BaseModel):
    id: uuid.UUID
    role: AgentRole
    content: str
    agent_name: str | None = None
    created_at: datetime


class ChatMessageResponse(BaseModel):
    reply: str
    draft_booking: BookingRead | None = None
    emergency: bool
