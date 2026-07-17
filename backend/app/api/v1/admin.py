import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import require_admin
from app.core.db import get_session
from app.core.exceptions import NotFoundError
from app.models.enums import BookingStatus
from app.models.user import User
from app.schemas.admin import (
    AccountRestoreRead,
    CompletionCorrectionRequest,
    DoctorVerificationQueueItem,
    DoctorVerifyRequest,
    FeatureFlagRead,
    FeatureFlagUpdate,
    PlatformStatsRead,
)
from app.schemas.booking import BookingRead
from app.schemas.pagination import Page, PageParams
from app.schemas.review import ReviewModerate, ReviewRead
from app.services import (
    account_deletion_service,
    admin_service,
    doctor_cache,
    feature_flag_service,
    review_service,
)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/doctors/pending", response_model=Page[DoctorVerificationQueueItem])
def list_pending_doctors(
    params: PageParams = Depends(), session: Session = Depends(get_session)
) -> Page[DoctorVerificationQueueItem]:
    doctors, total = admin_service.list_pending_doctors(session, offset=params.offset, limit=params.page_size)
    items = []
    for doctor in doctors:
        user = session.get(User, doctor.user_id)
        items.append(
            DoctorVerificationQueueItem(
                id=doctor.id,
                user_id=doctor.user_id,
                full_name=user.full_name if user else "",
                email=user.email if user else "",
                pmc_number=doctor.pmc_number,
                specialization_id=doctor.specialization_id,
                verification_status=doctor.verification_status,
            )
        )
    return Page.create(items, page=params.page, page_size=params.page_size, total=total)


@router.post("/doctors/{doctor_id}/verify", response_model=DoctorVerificationQueueItem)
def verify_doctor(
    doctor_id: uuid.UUID, body: DoctorVerifyRequest, session: Session = Depends(get_session)
) -> DoctorVerificationQueueItem:
    doctor = admin_service.verify_doctor(session, doctor_id=doctor_id, status=body.status, reason=body.reason)
    # F28: verification decides whether a doctor appears in search at all —
    # a revoked doctor must not linger in a cached results page.
    doctor_cache.invalidate_doctor(doctor.id)
    user = session.get(User, doctor.user_id)
    return DoctorVerificationQueueItem(
        id=doctor.id,
        user_id=doctor.user_id,
        full_name=user.full_name if user else "",
        email=user.email if user else "",
        pmc_number=doctor.pmc_number,
        specialization_id=doctor.specialization_id,
        verification_status=doctor.verification_status,
    )


@router.get("/bookings", response_model=Page[BookingRead])
def list_bookings(
    status: BookingStatus | None = None,
    doctor_id: uuid.UUID | None = None,
    params: PageParams = Depends(),
    session: Session = Depends(get_session),
) -> Page[BookingRead]:
    bookings, total = admin_service.list_bookings_for_oversight(
        session, status=status, doctor_id=doctor_id, offset=params.offset, limit=params.page_size
    )
    return Page.create(
        [BookingRead.model_validate(b, from_attributes=True) for b in bookings],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/bookings/{booking_id}", response_model=BookingRead)
def get_booking_detail(booking_id: uuid.UUID, session: Session = Depends(get_session)) -> BookingRead:
    booking = admin_service.get_booking_detail(session, booking_id=booking_id)
    return BookingRead.model_validate(booking, from_attributes=True)


@router.post("/bookings/{booking_id}/correct-completion", response_model=BookingRead)
def correct_booking_completion(
    booking_id: uuid.UUID, body: CompletionCorrectionRequest, session: Session = Depends(get_session)
) -> BookingRead:
    booking = admin_service.correct_booking_completion(session, booking_id=booking_id, target=body.target)
    return BookingRead.model_validate(booking, from_attributes=True)


@router.get("/reviews/pending", response_model=Page[ReviewRead])
def list_pending_reviews(
    params: PageParams = Depends(), session: Session = Depends(get_session)
) -> Page[ReviewRead]:
    reviews, total = review_service.list_pending_reviews(session, offset=params.offset, limit=params.page_size)
    return Page.create(
        [ReviewRead.model_validate(r, from_attributes=True) for r in reviews],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.post("/reviews/{review_id}/moderate", response_model=ReviewRead)
def moderate_review(
    review_id: uuid.UUID, body: ReviewModerate, session: Session = Depends(get_session)
) -> ReviewRead:
    review = review_service.moderate_review(session, review_id=review_id, status=body.status, reason=body.reason)
    return ReviewRead.model_validate(review, from_attributes=True)


@router.get("/stats", response_model=PlatformStatsRead)
def get_platform_stats(session: Session = Depends(get_session)) -> PlatformStatsRead:
    return PlatformStatsRead(**admin_service.get_platform_stats(session))


@router.post("/users/{user_id}/restore", response_model=AccountRestoreRead)
def restore_deleted_account(user_id: uuid.UUID, session: Session = Depends(get_session)) -> AccountRestoreRead:
    """F27 — support-mediated undo inside the 30-day grace window. The owner
    can't do this themselves: deletion deactivates the account, so they
    can't log in to reach it (see account_deletion_service.cancel_deletion)."""
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("user not found")

    restored = account_deletion_service.cancel_deletion(session, user=user)
    return AccountRestoreRead(
        user_id=restored.id,
        email=restored.email,
        is_active=restored.is_active,
        deleted_at=restored.deleted_at,
    )


@router.get("/feature-flags", response_model=list[FeatureFlagRead])
def list_feature_flags(session: Session = Depends(get_session)) -> list[FeatureFlagRead]:
    """F29 — flags are an opt-*out* switch: a key with no row reads as
    enabled (see feature_flag_service.is_enabled), so this lists the known
    keys with their effective state rather than only the rows that happen
    to exist."""
    return [
        FeatureFlagRead(key=key, enabled=feature_flag_service.is_enabled(session, key))
        for key in feature_flag_service.KNOWN_FLAGS
    ]


@router.put("/feature-flags/{key}", response_model=FeatureFlagRead)
def set_feature_flag(
    key: str, body: FeatureFlagUpdate, session: Session = Depends(get_session)
) -> FeatureFlagRead:
    if key not in feature_flag_service.KNOWN_FLAGS:
        raise NotFoundError(f"unknown feature flag {key!r}")

    flag = feature_flag_service.set_enabled(session, key=key, enabled=body.enabled)
    return FeatureFlagRead(key=flag.key, enabled=flag.enabled)
