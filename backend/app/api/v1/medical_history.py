import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import require_doctor, require_patient, resolve_owned_patient_profile
from app.core.db import get_session
from app.models.user import User
from app.schemas.medical_history import MedicalHistoryRead, MedicalHistoryWrite
from app.services import audit_service, doctor_service, medical_history_service

router = APIRouter()


@router.put("/patient-profiles/{profile_id}/medical-history", response_model=MedicalHistoryRead)
def write_medical_history(
    profile_id: uuid.UUID,
    body: MedicalHistoryWrite,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> MedicalHistoryRead:
    patient_profile = resolve_owned_patient_profile(session, user, profile_id)
    history = medical_history_service.upsert(
        session,
        patient_profile=patient_profile,
        editor_user_id=user.id,
        blood_group=body.blood_group,
        allergies=body.allergies,
        medications=body.medications,
        chronic_conditions=body.chronic_conditions,
        surgeries=body.surgeries,
    )
    audit_service.log(
        session, actor_user_id=user.id, action="write", resource_type="medical_history", resource_id=history.id
    )
    return MedicalHistoryRead.model_validate(history, from_attributes=True)


@router.get("/patient-profiles/{profile_id}/medical-history", response_model=MedicalHistoryRead)
def read_medical_history(
    profile_id: uuid.UUID,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> MedicalHistoryRead:
    patient_profile = resolve_owned_patient_profile(session, user, profile_id)
    history = medical_history_service.get_current_for_patient(session, patient_profile=patient_profile)
    audit_service.log(
        session, actor_user_id=user.id, action="read", resource_type="medical_history", resource_id=history.id
    )
    return MedicalHistoryRead.model_validate(history, from_attributes=True)


@router.get("/patient-profiles/{profile_id}/medical-history/versions", response_model=list[MedicalHistoryRead])
def list_medical_history_versions(
    profile_id: uuid.UUID,
    user: User = Depends(require_patient),
    session: Session = Depends(get_session),
) -> list[MedicalHistoryRead]:
    patient_profile = resolve_owned_patient_profile(session, user, profile_id)
    versions = medical_history_service.list_versions(session, patient_profile=patient_profile)
    audit_service.log(
        session,
        actor_user_id=user.id,
        action="read_history",
        resource_type="medical_history",
        resource_id=patient_profile.id,
    )
    return [MedicalHistoryRead.model_validate(v, from_attributes=True) for v in versions]


@router.get("/bookings/{booking_id}/medical-history", response_model=MedicalHistoryRead)
def read_medical_history_for_doctor(
    booking_id: uuid.UUID,
    user: User = Depends(require_doctor),
    session: Session = Depends(get_session),
) -> MedicalHistoryRead:
    doctor = doctor_service.get_doctor_profile_for_user(session, user)
    history = medical_history_service.get_for_doctor_via_booking(session, doctor=doctor, booking_id=booking_id)
    audit_service.log(
        session, actor_user_id=user.id, action="read", resource_type="medical_history", resource_id=history.id
    )
    return MedicalHistoryRead.model_validate(history, from_attributes=True)
