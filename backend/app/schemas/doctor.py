import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field

from app.models.enums import DoctorVerificationStatus, Weekday


class SpecializationRead(BaseModel):
    id: uuid.UUID
    slug: str
    name_en: str
    name_ur: str | None = None


class ClinicLocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=500)
    city: str = Field(min_length=1, max_length=100)
    map_embed_url: str | None = None


class ClinicLocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    map_embed_url: str | None = None


class ClinicLocationRead(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    name: str
    address: str
    city: str
    map_embed_url: str | None = None
    is_active: bool


class DoctorProfileUpdate(BaseModel):
    qualifications: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    consultation_fee: int | None = Field(default=None, gt=0, le=1_000_000)
    cancellation_policy_hours: int | None = Field(default=None, ge=1, le=72)


class DoctorProfileRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    specialization: SpecializationRead
    qualifications: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    consultation_fee: int
    verification_status: DoctorVerificationStatus
    cancellation_policy_hours: int
    clinic_locations: list[ClinicLocationRead] = []


class DoctorSearchResult(BaseModel):
    id: uuid.UUID
    full_name: str
    specialization: SpecializationRead
    consultation_fee: int
    cities: list[str]
    photo_url: str | None = None
    next_available_slot_utc: datetime | None = None


class AvailabilityRuleCreate(BaseModel):
    clinic_location_id: uuid.UUID
    weekday: Weekday
    start_time_local: time
    end_time_local: time
    slot_duration_minutes: int = Field(default=30, ge=5, le=240)


class AvailabilityRuleRead(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    clinic_location_id: uuid.UUID
    weekday: Weekday
    start_time_local: time
    end_time_local: time
    slot_duration_minutes: int
    is_active: bool


class AvailabilityExceptionCreate(BaseModel):
    clinic_location_id: uuid.UUID | None = None
    exception_date: date
    reason: str | None = None


class AvailabilityExceptionRead(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    clinic_location_id: uuid.UUID | None = None
    exception_date: date
    reason: str | None = None


class SlotRead(BaseModel):
    clinic_location_id: uuid.UUID
    start_time_utc: datetime
    end_time_utc: datetime
