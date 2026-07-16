import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_active_patient_profile
from app.core.db import get_session
from app.models.user import PatientProfile
from app.schemas.waitlist import WaitlistJoinRequest, WaitlistRead
from app.services import feature_flag_service, waitlist_service

router = APIRouter(dependencies=[Depends(feature_flag_service.require_feature(feature_flag_service.WAITLIST))])


@router.post("", response_model=WaitlistRead, status_code=201)
def join_waitlist(
    body: WaitlistJoinRequest,
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> WaitlistRead:
    entry = waitlist_service.join_waitlist(
        session,
        patient_profile=patient_profile,
        doctor_id=body.doctor_id,
        clinic_location_id=body.clinic_location_id,
        start_time_utc=body.start_time_utc,
        end_time_utc=body.end_time_utc,
    )
    return WaitlistRead.model_validate(entry, from_attributes=True)


@router.get("/me", response_model=list[WaitlistRead])
def list_my_waitlist_entries(
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> list[WaitlistRead]:
    entries = waitlist_service.list_for_patient(session, patient_profile=patient_profile)
    return [WaitlistRead.model_validate(e, from_attributes=True) for e in entries]


@router.delete("/{waitlist_id}", response_model=WaitlistRead)
def leave_waitlist(
    waitlist_id: uuid.UUID,
    patient_profile: PatientProfile = Depends(get_active_patient_profile),
    session: Session = Depends(get_session),
) -> WaitlistRead:
    entry = waitlist_service.leave_waitlist(session, patient_profile=patient_profile, waitlist_id=waitlist_id)
    return WaitlistRead.model_validate(entry, from_attributes=True)
