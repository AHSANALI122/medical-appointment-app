import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import require_doctor
from app.core.db import get_session
from app.models.user import User
from app.schemas.review import ReviewReply, ReviewRead
from app.services import doctor_service, review_service

router = APIRouter()


@router.post("/{review_id}/reply", response_model=ReviewRead)
def reply_to_review(
    review_id: uuid.UUID,
    body: ReviewReply,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> ReviewRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    review = review_service.doctor_reply_to_review(
        session, review_id=review_id, doctor_id=doctor.id, reply=body.reply
    )
    return ReviewRead.model_validate(review, from_attributes=True)
