import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.deps import require_doctor
from app.core.db import get_session
from app.core.exceptions import NotFoundError
from app.models.taxonomy import SpecializationTaxonomy
from app.models.user import User
from app.schemas.doctor import (
    AvailabilityExceptionCreate,
    AvailabilityExceptionRead,
    AvailabilityRuleCreate,
    AvailabilityRuleRead,
    AvailabilityRuleUpdate,
    ClinicLocationCreate,
    ClinicLocationRead,
    ClinicLocationUpdate,
    DoctorProfileRead,
    DoctorProfileUpdate,
    DoctorSearchResult,
    SlotRead,
    SpecializationRead,
)
from app.schemas.pagination import Page, PageParams
from app.schemas.review import ReviewRead
from app.services import doctor_service, review_service
from app.services.doctor_service import DoctorSortOrder
from app.services.slot_service import MAX_HORIZON, generate_available_slots, next_available_slot_for_doctor

router = APIRouter()


def _specialization_read(session: Session, specialization_id: uuid.UUID) -> SpecializationRead:
    spec = session.get(SpecializationTaxonomy, specialization_id)
    if spec is None:
        raise NotFoundError("specialization not found")
    return SpecializationRead.model_validate(spec, from_attributes=True)


@router.get("/specializations", response_model=list[SpecializationRead])
def list_specializations(session: Session = Depends(get_session)) -> list[SpecializationRead]:
    specs = session.exec(
        select(SpecializationTaxonomy).where(SpecializationTaxonomy.is_active == True)  # noqa: E712
    ).all()
    return [SpecializationRead.model_validate(s, from_attributes=True) for s in specs]


@router.get("", response_model=Page[DoctorSearchResult])
def search_doctors(
    specialization_id: uuid.UUID | None = None,
    city: str | None = None,
    fee_min: int | None = None,
    fee_max: int | None = None,
    name: str | None = Query(default=None, min_length=1, max_length=200),
    sort: DoctorSortOrder = DoctorSortOrder.NAME,
    params: PageParams = Depends(),
    session: Session = Depends(get_session),
) -> Page[DoctorSearchResult]:
    doctors, total = doctor_service.search_doctors(
        session,
        specialization_id=specialization_id,
        city=city,
        fee_min=fee_min,
        fee_max=fee_max,
        name=name,
        sort=sort,
        offset=params.offset,
        limit=params.page_size,
    )
    results = []
    for doctor in doctors:
        user = session.get(User, doctor.user_id)
        locations = doctor_service.list_clinic_locations(session, doctor.id)
        avg_rating, review_count = review_service.get_doctor_rating_summary(session, doctor_id=doctor.id)
        results.append(
            DoctorSearchResult(
                id=doctor.id,
                full_name=user.full_name if user else "",
                specialization=_specialization_read(session, doctor.specialization_id),
                consultation_fee=doctor.consultation_fee,
                cities=sorted({loc.city for loc in locations}),
                photo_url=doctor.photo_url,
                # Computed only for this page's rows (bounded by page_size),
                # never across the full doctor corpus — see slot_service.
                next_available_slot_utc=next_available_slot_for_doctor(session, doctor_id=doctor.id),
                average_rating=avg_rating,
                review_count=review_count,
            )
        )
    return Page.create(results, page=params.page, page_size=params.page_size, total=total)


@router.get("/{doctor_id}/reviews", response_model=Page[ReviewRead])
def list_doctor_reviews(
    doctor_id: uuid.UUID,
    params: PageParams = Depends(),
    session: Session = Depends(get_session),
) -> Page[ReviewRead]:
    doctor_service.get_doctor_profile_or_404(session, doctor_id)
    reviews, total = review_service.list_public_doctor_reviews(
        session, doctor_id=doctor_id, offset=params.offset, limit=params.page_size
    )
    return Page.create(
        [ReviewRead.model_validate(r, from_attributes=True) for r in reviews],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/me", response_model=DoctorProfileRead)
def get_my_profile(
    user: User = Depends(require_doctor), session: Session = Depends(get_session)
) -> DoctorProfileRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    return _doctor_profile_read(session, doctor, user)


@router.patch("/me", response_model=DoctorProfileRead)
def update_my_profile(
    body: DoctorProfileUpdate,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> DoctorProfileRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(doctor, field, value)
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return _doctor_profile_read(session, doctor, user)


@router.post("/me/clinics", response_model=ClinicLocationRead, status_code=201)
def add_clinic(
    body: ClinicLocationCreate,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> ClinicLocationRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    location = doctor_service.add_clinic_location(
        session,
        doctor_id=doctor.id,
        name=body.name,
        address=body.address,
        city=body.city,
        map_embed_url=body.map_embed_url,
    )
    return ClinicLocationRead.model_validate(location, from_attributes=True)


@router.patch("/me/clinics/{clinic_location_id}", response_model=ClinicLocationRead)
def update_clinic(
    clinic_location_id: uuid.UUID,
    body: ClinicLocationUpdate,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> ClinicLocationRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    location = doctor_service.update_clinic_location(
        session,
        doctor_id=doctor.id,
        clinic_location_id=clinic_location_id,
        name=body.name,
        address=body.address,
        city=body.city,
        map_embed_url=body.map_embed_url,
    )
    return ClinicLocationRead.model_validate(location, from_attributes=True)


@router.get("/me/clinics", response_model=list[ClinicLocationRead])
def list_my_clinics(
    user: User = Depends(require_doctor), session: Session = Depends(get_session)
) -> list[ClinicLocationRead]:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    locations = doctor_service.list_clinic_locations(session, doctor.id)
    return [ClinicLocationRead.model_validate(loc, from_attributes=True) for loc in locations]


@router.post("/me/availability-rules", response_model=AvailabilityRuleRead, status_code=201)
def add_availability_rule(
    body: AvailabilityRuleCreate,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> AvailabilityRuleRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    rule = doctor_service.add_availability_rule(
        session,
        doctor_id=doctor.id,
        clinic_location_id=body.clinic_location_id,
        weekday=body.weekday,
        start_time_local=body.start_time_local,
        end_time_local=body.end_time_local,
        slot_duration_minutes=body.slot_duration_minutes,
    )
    return AvailabilityRuleRead.model_validate(rule, from_attributes=True)


@router.get("/me/availability-rules", response_model=list[AvailabilityRuleRead])
def list_my_availability_rules(
    user: User = Depends(require_doctor), session: Session = Depends(get_session)
) -> list[AvailabilityRuleRead]:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    rules = doctor_service.list_availability_rules(session, doctor.id)
    return [AvailabilityRuleRead.model_validate(r, from_attributes=True) for r in rules]


@router.patch("/me/availability-rules/{rule_id}", response_model=AvailabilityRuleRead)
def update_my_availability_rule(
    rule_id: uuid.UUID,
    body: AvailabilityRuleUpdate,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> AvailabilityRuleRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    rule = doctor_service.update_availability_rule(
        session,
        doctor_id=doctor.id,
        rule_id=rule_id,
        start_time_local=body.start_time_local,
        end_time_local=body.end_time_local,
        slot_duration_minutes=body.slot_duration_minutes,
        is_active=body.is_active,
    )
    return AvailabilityRuleRead.model_validate(rule, from_attributes=True)


@router.delete("/me/availability-rules/{rule_id}", status_code=204)
def delete_my_availability_rule(
    rule_id: uuid.UUID,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> None:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    doctor_service.delete_availability_rule(session, doctor_id=doctor.id, rule_id=rule_id)


@router.get("/me/availability-exceptions", response_model=list[AvailabilityExceptionRead])
def list_my_availability_exceptions(
    user: User = Depends(require_doctor), session: Session = Depends(get_session)
) -> list[AvailabilityExceptionRead]:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    exceptions = doctor_service.list_availability_exceptions(session, doctor.id)
    return [AvailabilityExceptionRead.model_validate(e, from_attributes=True) for e in exceptions]


@router.delete("/me/availability-exceptions/{exception_id}", status_code=204)
def delete_my_availability_exception(
    exception_id: uuid.UUID,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> None:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    doctor_service.delete_availability_exception(session, doctor_id=doctor.id, exception_id=exception_id)


@router.post("/me/availability-exceptions", response_model=AvailabilityExceptionRead, status_code=201)
def add_availability_exception(
    body: AvailabilityExceptionCreate,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> AvailabilityExceptionRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    exception = doctor_service.add_availability_exception(
        session,
        doctor_id=doctor.id,
        clinic_location_id=body.clinic_location_id,
        exception_date=body.exception_date,
        reason=body.reason,
    )
    return AvailabilityExceptionRead.model_validate(exception, from_attributes=True)


@router.get("/{doctor_id}", response_model=DoctorProfileRead)
def get_doctor_profile(doctor_id: uuid.UUID, session: Session = Depends(get_session)) -> DoctorProfileRead:
    doctor = doctor_service.get_doctor_profile_or_404(session, doctor_id)
    user = session.get(User, doctor.user_id)
    return _doctor_profile_read(session, doctor, user)


@router.get("/{doctor_id}/slots", response_model=list[SlotRead])
def get_doctor_slots(
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID,
    from_date: date = Query(default_factory=date.today),
    to_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[SlotRead]:
    doctor_service.get_doctor_profile_or_404(session, doctor_id)
    resolved_to_date = to_date or (from_date + timedelta(days=14))
    max_to_date = date.today() + MAX_HORIZON
    if resolved_to_date > max_to_date:
        resolved_to_date = max_to_date
    return generate_available_slots(
        session,
        doctor_id=doctor_id,
        clinic_location_id=clinic_location_id,
        from_date=from_date,
        to_date=resolved_to_date,
    )


def _doctor_profile_read(session: Session, doctor, user: User | None) -> DoctorProfileRead:
    locations = doctor_service.list_clinic_locations(session, doctor.id)
    avg_rating, review_count = review_service.get_doctor_rating_summary(session, doctor_id=doctor.id)
    return DoctorProfileRead(
        id=doctor.id,
        user_id=doctor.user_id,
        full_name=user.full_name if user else "",
        specialization=_specialization_read(session, doctor.specialization_id),
        qualifications=doctor.qualifications,
        bio=doctor.bio,
        photo_url=doctor.photo_url,
        consultation_fee=doctor.consultation_fee,
        verification_status=doctor.verification_status,
        cancellation_policy_hours=doctor.cancellation_policy_hours,
        clinic_locations=[ClinicLocationRead.model_validate(loc, from_attributes=True) for loc in locations],
        average_rating=avg_rating,
        review_count=review_count,
    )
