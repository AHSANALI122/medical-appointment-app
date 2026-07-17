import uuid
from enum import StrEnum

from sqlmodel import Session, func, select

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.doctor import AvailabilityException, AvailabilityRule, ClinicLocation, DoctorProfile
from app.models.enums import DoctorVerificationStatus
from app.models.user import User


class DoctorSortOrder(StrEnum):
    NAME = "name"
    FEE_ASC = "fee_asc"
    FEE_DESC = "fee_desc"


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


def update_clinic_location(
    session: Session,
    *,
    doctor_id: uuid.UUID,
    clinic_location_id: uuid.UUID,
    name: str | None,
    address: str | None,
    city: str | None,
    map_embed_url: str | None,
) -> ClinicLocation:
    """Edits a clinic's live address. Past bookings keep their own
    `address_snapshot` string copied at draft time (F8) — this never
    rewrites history, it only changes what's shown for future bookings."""
    location = _assert_owns_clinic(session, doctor_id, clinic_location_id)
    if name is not None:
        location.name = name
    if address is not None:
        location.address = address
    if city is not None:
        location.city = city
    if map_embed_url is not None:
        location.map_embed_url = map_embed_url
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


def list_clinic_locations_for_doctors(
    session: Session, doctor_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ClinicLocation]]:
    """Batched form of `list_clinic_locations` for list endpoints (F28 N+1
    prevention). Every requested id gets a key, so a doctor with no active
    clinic yields [] rather than a KeyError."""
    if not doctor_ids:
        return {}

    locations = session.exec(
        select(ClinicLocation).where(
            ClinicLocation.doctor_id.in_(doctor_ids),
            ClinicLocation.is_active == True,  # noqa: E712
        )
    ).all()

    grouped: dict[uuid.UUID, list[ClinicLocation]] = {doctor_id: [] for doctor_id in doctor_ids}
    for location in locations:
        grouped[location.doctor_id].append(location)
    return grouped


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


def _get_owned_rule(session: Session, doctor_id: uuid.UUID, rule_id: uuid.UUID) -> AvailabilityRule:
    rule = session.get(AvailabilityRule, rule_id)
    if rule is None or rule.doctor_id != doctor_id:
        raise NotFoundError("availability rule not found")
    return rule


def update_availability_rule(
    session: Session,
    *,
    doctor_id: uuid.UUID,
    rule_id: uuid.UUID,
    start_time_local=None,
    end_time_local=None,
    slot_duration_minutes: int | None = None,
    is_active: bool | None = None,
) -> AvailabilityRule:
    rule = _get_owned_rule(session, doctor_id, rule_id)
    if start_time_local is not None:
        rule.start_time_local = start_time_local
    if end_time_local is not None:
        rule.end_time_local = end_time_local
    if slot_duration_minutes is not None:
        rule.slot_duration_minutes = slot_duration_minutes
    if is_active is not None:
        rule.is_active = is_active
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def delete_availability_rule(session: Session, *, doctor_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    rule = _get_owned_rule(session, doctor_id, rule_id)
    session.delete(rule)
    session.commit()


def list_availability_rules(session: Session, doctor_id: uuid.UUID) -> list[AvailabilityRule]:
    return list(
        session.exec(select(AvailabilityRule).where(AvailabilityRule.doctor_id == doctor_id)).all()
    )


def list_availability_exceptions(session: Session, doctor_id: uuid.UUID) -> list[AvailabilityException]:
    return list(
        session.exec(
            select(AvailabilityException).where(AvailabilityException.doctor_id == doctor_id)
        ).all()
    )


def delete_availability_exception(
    session: Session, *, doctor_id: uuid.UUID, exception_id: uuid.UUID
) -> None:
    """Ends a leave/holiday early (F13 leave management) — the affected-bookings
    auto-flag flow for *newly added* leave belongs to F3 slot generation and
    isn't re-triggered by removing one."""
    exception = session.get(AvailabilityException, exception_id)
    if exception is None or exception.doctor_id != doctor_id:
        raise NotFoundError("availability exception not found")
    session.delete(exception)
    session.commit()


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
    name: str | None = None,
    sort: DoctorSortOrder = DoctorSortOrder.NAME,
    offset: int,
    limit: int,
) -> tuple[list[DoctorProfile], int]:
    # Only `verified` doctors are searchable/bookable (F23) — this is the one
    # server-enforced gate that makes the acceptance criterion true no matter
    # what filters/sort a client requests.
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
        # A subquery rather than a join — a doctor with multiple clinics in
        # the same city must appear once, not once per matching clinic row.
        query = query.where(
            DoctorProfile.id.in_(select(ClinicLocation.doctor_id).where(ClinicLocation.city == city))
        )

    needs_user_join = name is not None or sort == DoctorSortOrder.NAME
    if needs_user_join:
        query = query.join(User, User.id == DoctorProfile.user_id)
    if name is not None:
        # ILIKE against users.full_name, backed by a pg_trgm GIN index
        # (see migration) so this stays fast at 10k-doctor scale (F10 p95).
        query = query.where(User.full_name.ilike(f"%{name}%"))

    total = session.exec(
        select(func.count()).select_from(query.with_only_columns(DoctorProfile.id).subquery())
    ).one()

    if sort == DoctorSortOrder.FEE_ASC:
        query = query.order_by(DoctorProfile.consultation_fee.asc())
    elif sort == DoctorSortOrder.FEE_DESC:
        query = query.order_by(DoctorProfile.consultation_fee.desc())
    else:
        query = query.order_by(User.full_name.asc())

    page_items = list(session.exec(query.offset(offset).limit(limit)).all())
    return page_items, total
