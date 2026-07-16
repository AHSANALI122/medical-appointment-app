import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import DoctorVerificationStatus, UserRole


class RegisterPatientRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=32)


class RegisterDoctorRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    pmc_number: str = Field(min_length=1, max_length=64)
    specialization_id: uuid.UUID
    consultation_fee: int = Field(gt=0, le=1_000_000)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    phone: str | None = None


class DoctorRegisterResponse(BaseModel):
    user: UserPublic
    verification_status: DoctorVerificationStatus
