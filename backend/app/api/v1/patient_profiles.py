from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import require_patient
from app.core.db import get_session
from app.models.user import User
from app.schemas.patient_profile import PatientProfileCreate, PatientProfileRead
from app.services import feature_flag_service, patient_profile_service

router = APIRouter(dependencies=[Depends(feature_flag_service.require_feature(feature_flag_service.FAMILY_ACCOUNTS))])


@router.post("", response_model=PatientProfileRead, status_code=201)
def add_dependent_profile(
    body: PatientProfileCreate,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> PatientProfileRead:
    profile = patient_profile_service.create_dependent_profile(
        session,
        user_id=user.id,
        full_name=body.full_name,
        relationship_label=body.relationship_label,
        date_of_birth=body.date_of_birth,
    )
    return PatientProfileRead.model_validate(profile, from_attributes=True)


@router.get("", response_model=list[PatientProfileRead])
def list_my_profiles(
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> list[PatientProfileRead]:
    profiles = patient_profile_service.list_profiles_for_user(session, user_id=user.id)
    return [PatientProfileRead.model_validate(p, from_attributes=True) for p in profiles]
