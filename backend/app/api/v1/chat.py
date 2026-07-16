import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.agents.runner import run_agent_turn
from app.api.deps import require_patient
from app.core.db import get_session
from app.core.rate_limit import CHAT_RATE_LIMIT, rate_limit
from app.models.booking import Booking
from app.models.user import User
from app.schemas.booking import BookingRead
from app.schemas.chat import ChatMessageCreate, ChatMessageRead, ChatMessageResponse, ChatSessionRead
from app.schemas.pagination import Page, PageParams
from app.services import agent_session_service

router = APIRouter()

_tier, _limit, _window = CHAT_RATE_LIMIT
_chat_rate_limit = Depends(rate_limit(_tier, limit=_limit, window_seconds=_window))


@router.post("/sessions", response_model=ChatSessionRead)
def create_or_get_session(
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> ChatSessionRead:
    agent_session = agent_session_service.get_or_create_session(session, user_id=user.id)
    return ChatSessionRead.model_validate(agent_session, from_attributes=True)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageResponse,
    dependencies=[_chat_rate_limit],
)
async def send_message(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> ChatMessageResponse:
    agent_session = agent_session_service.get_owned_session(
        session, session_id=session_id, user_id=user.id
    )
    result = await run_agent_turn(
        session, user=user, agent_session=agent_session, user_message=body.message
    )

    draft_booking = None
    if result.draft_booking_id is not None:
        booking = session.get(Booking, result.draft_booking_id)
        if booking is not None:
            draft_booking = BookingRead.model_validate(booking, from_attributes=True)

    return ChatMessageResponse(reply=result.reply, draft_booking=draft_booking, emergency=result.emergency)


@router.get("/sessions/{session_id}/messages", response_model=Page[ChatMessageRead])
def get_messages(
    session_id: uuid.UUID,
    params: PageParams = Depends(),
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> Page[ChatMessageRead]:
    agent_session = agent_session_service.get_owned_session(
        session, session_id=session_id, user_id=user.id
    )
    messages, total = agent_session_service.list_messages(
        session, agent_session=agent_session, offset=params.offset, limit=params.page_size
    )
    return Page.create(
        [ChatMessageRead.model_validate(m, from_attributes=True) for m in messages],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )
