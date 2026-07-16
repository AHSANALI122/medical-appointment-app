import asyncio
import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.api.deps import get_active_patient_profile, require_doctor, require_patient
from app.core.db import get_session
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.user import PatientProfile, User
from app.schemas.booking import BookingRead, CancelRequest, CreateDraftRequest, RejectRequest
from app.schemas.pagination import Page, PageParams
from app.services import booking_service, doctor_service

router = APIRouter()


@router.post("", response_model=BookingRead, status_code=201)
def create_draft(
    body: CreateDraftRequest,
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> BookingRead:
    booking = booking_service.create_draft_booking(
        session,
        patient_profile=patient_profile,
        doctor_id=body.doctor_id,
        clinic_location_id=body.clinic_location_id,
        start_time_utc=body.start_time_utc,
        end_time_utc=body.end_time_utc,
    )
    return BookingRead.model_validate(booking, from_attributes=True)


@router.get("/me", response_model=Page[BookingRead])
def list_my_bookings(
    status: BookingStatus | None = None,
    params: PageParams = Depends(),
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> Page[BookingRead]:
    bookings = booking_service.list_patient_bookings(session, patient_profile=patient_profile, status=status)
    total = len(bookings)
    page_items = bookings[params.offset : params.offset + params.page_size]
    return Page.create(
        [BookingRead.model_validate(b, from_attributes=True) for b in page_items],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/doctor/me", response_model=Page[BookingRead])
def list_doctor_bookings(
    status: BookingStatus | None = None,
    params: PageParams = Depends(),
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> Page[BookingRead]:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    bookings = booking_service.list_doctor_bookings(session, doctor=doctor, status=status)
    total = len(bookings)
    page_items = bookings[params.offset : params.offset + params.page_size]
    return Page.create(
        [BookingRead.model_validate(b, from_attributes=True) for b in page_items],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/{booking_id}", response_model=BookingRead)
def get_booking(
    booking_id: uuid.UUID,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> BookingRead:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFoundError("booking not found")

    owner_profile = session.exec(
        select(PatientProfile).where(
            PatientProfile.id == booking.patient_profile_id, PatientProfile.user_id == user.id
        )
    ).first()
    if owner_profile is None:
        raise ForbiddenError("you do not have access to this booking")

    return BookingRead.model_validate(booking, from_attributes=True)


@router.post("/{booking_id}/confirm", response_model=BookingRead)
def confirm_booking(
    booking_id: uuid.UUID,
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> BookingRead:
    booking = booking_service.confirm_booking(session, booking_id=booking_id, patient_profile=patient_profile)
    return BookingRead.model_validate(booking, from_attributes=True)


@router.post("/{booking_id}/cancel", response_model=BookingRead)
def cancel_booking(
    booking_id: uuid.UUID,
    body: CancelRequest,
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> BookingRead:
    booking = booking_service.patient_cancel_booking(
        session, booking_id=booking_id, patient_profile=patient_profile, reason=body.reason
    )
    return BookingRead.model_validate(booking, from_attributes=True)


@router.post("/{booking_id}/accept", response_model=BookingRead)
def accept_booking(
    booking_id: uuid.UUID,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> BookingRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    booking = booking_service.doctor_accept_booking(session, booking_id=booking_id, doctor=doctor)
    return BookingRead.model_validate(booking, from_attributes=True)


@router.post("/{booking_id}/reject", response_model=BookingRead)
def reject_booking(
    booking_id: uuid.UUID,
    body: RejectRequest,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> BookingRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    booking = booking_service.doctor_reject_booking(
        session, booking_id=booking_id, doctor=doctor, reason=body.reason
    )
    return BookingRead.model_validate(booking, from_attributes=True)


@router.post("/{booking_id}/doctor-cancel", response_model=BookingRead)
def doctor_cancel_booking(
    booking_id: uuid.UUID,
    body: CancelRequest,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> BookingRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    booking = booking_service.doctor_cancel_booking(
        session, booking_id=booking_id, doctor=doctor, reason=body.reason
    )
    return BookingRead.model_validate(booking, from_attributes=True)


@router.get("/me/stream")
async def stream_my_bookings(
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """SSE stream of the patient's booking statuses; polls the DB server-side
    every 2s and emits only on change, so the dashboard reflects state
    transitions (F5) without the client needing to poll itself."""

    async def event_source():
        last_snapshot: dict[str, str] = {}
        for _ in range(150):  # ~5 minutes per connection; client reconnects (standard SSE behavior)
            bookings = booking_service.list_patient_bookings(session, patient_profile=patient_profile)
            snapshot = {str(b.id): b.status.value for b in bookings}
            if snapshot != last_snapshot:
                payload = [
                    {"id": str(b.id), "status": b.status.value, "updated_at": b.updated_at.isoformat()}
                    for b in bookings
                ]
                yield f"data: {json.dumps(payload)}\n\n"
                last_snapshot = snapshot
            await asyncio.sleep(2)

    return StreamingResponse(event_source(), media_type="text/event-stream")
