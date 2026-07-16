import uuid

from sqlmodel import Session, func, select

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.doctor import AvailabilityException, AvailabilityRule, ClinicLocation, DoctorProfile
from app.models.enums import DoctorVerificationStatus
from app.models.user import User


def get_doctor_profile_for_user(session: Session, user: User) -> DoctorProfile:
    profile = session.exec(
        select(DoctorProfile).where(DoctorProfile.user_id == user.id)
    ).first()
    if profile is None:
        raise NotFoundError("doctor profile not found")
    return profile


def get_doctor_profile_or_404(session: Session, doctor_id: uuid.UUID) -> DoctorProfile:
    profile = session.get(DoctorProfile, doctor_id)
    if profile is None:
        raise NotFoundError("doctor not found")
    return profile


def _assert_owns_clinic(session: Session, doctor_id: uuid.UUID, clinic_location_id: uuid.UUID) -> ClinicLocation:
    location = session.get(ClinicLocation, clinic_location_id)
    if location is None or location.doctor_id != doctor_id:
        raise ForbiddenError("clinic location does not belong to this doctor")
    return location


def add_clinic_location(
    session: Session, *, doctor_id: uuid.UUID, name: str, address: str, city: str, map_embed_url: str | None
) -> ClinicLocation:
    location = ClinicLocation(
        doctor_id=doctor_id, name=name, address=address, city=city, map_embed_url=map_embed_url
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def list_clinic_locations(session: Session, doctor_id: uuid.UUID) -> list[ClinicLocation]:
    return list(
        session.exec(
            select(ClinicLocation).where(
                ClinicLocation.doctor_id == doctor_id, ClinicLocation.is_active == True  # noqa: E712
            )
        ).all()
    )


def add_availability_rule(
    session: Session,
    *,
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID,
    weekday,
    start_time_local,
    end_time_local,
    slot_duration_minutes: int,
) -> AvailabilityRule:
    _assert_owns_clinic(session, doctor_id, clinic_location_id)
    rule = AvailabilityRule(
        doctor_id=doctor_id,
        clinic_location_id=clinic_location_id,
        weekday=weekday,
        start_time_local=start_time_local,
        end_time_local=end_time_local,
        slot_duration_minutes=slot_duration_minutes,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def add_availability_exception(
    session: Session,
    *,
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID | None,
    exception_date,
    reason: str | None,
) -> AvailabilityException:
    if clinic_location_id is not None:
        _assert_owns_clinic(session, doctor_id, clinic_location_id)
    exception = AvailabilityException(
        doctor_id=doctor_id,
        clinic_location_id=clinic_location_id,
        exception_date=exception_date,
        reason=reason,
    )
    session.add(exception)
    session.commit()
    session.refresh(exception)
    return exception


def search_doctors(
    session: Session,
    *,
    specialization_id: uuid.UUID | None,
    city: str | None,
    fee_min: int | None,
    fee_max: int | None,
    offset: int,
    limit: int,
) -> tuple[list[DoctorProfile], int]:
    query = select(DoctorProfile).where(
        DoctorProfile.verification_status == DoctorVerificationStatus.VERIFIED
    )
    if specialization_id is not None:
        query = query.where(DoctorProfile.specialization_id == specialization_id)
    if fee_min is not None:
        query = query.where(DoctorProfile.consultation_fee >= fee_min)
    if fee_max is not None:
        query = query.where(DoctorProfile.consultation_fee <= fee_max)

    if city is not None:
        query = query.join(ClinicLocation).where(ClinicLocation.city == city)

    total = session.exec(
        select(func.count()).select_from(query.with_only_columns(DoctorProfile.id).subquery())
    ).one()
    page_items = list(session.exec(query.offset(offset).limit(limit)).all())
    return page_items, total
