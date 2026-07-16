export type UserRole = "patient" | "doctor" | "admin";

export type DoctorVerificationStatus = "unverified" | "verified" | "rejected";

export type BookingStatus =
  | "draft"
  | "pending"
  | "confirmed"
  | "completed"
  | "cancelled"
  | "rejected"
  | "expired"
  | "no_show";

export type BookingSource = "user" | "system_waitlist";
export type CancelledBy = "patient" | "doctor" | "admin";
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export interface UserPublic {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  phone: string | null;
}

export interface DoctorRegisterResponse {
  user: UserPublic;
  verification_status: DoctorVerificationStatus;
}

export interface SpecializationRead {
  id: string;
  slug: string;
  name_en: string;
  name_ur: string | null;
}

export interface ClinicLocationRead {
  id: string;
  doctor_id: string;
  name: string;
  address: string;
  city: string;
  map_embed_url: string | null;
  is_active: boolean;
}

export interface DoctorProfileRead {
  id: string;
  user_id: string;
  full_name: string;
  specialization: SpecializationRead;
  qualifications: string | null;
  bio: string | null;
  photo_url: string | null;
  consultation_fee: number;
  verification_status: DoctorVerificationStatus;
  cancellation_policy_hours: number;
  clinic_locations: ClinicLocationRead[];
}

export interface DoctorSearchResult {
  id: string;
  full_name: string;
  specialization: SpecializationRead;
  consultation_fee: number;
  cities: string[];
  photo_url: string | null;
}

export interface AvailabilityRuleRead {
  id: string;
  doctor_id: string;
  clinic_location_id: string;
  weekday: Weekday;
  start_time_local: string;
  end_time_local: string;
  slot_duration_minutes: number;
  is_active: boolean;
}

export interface SlotRead {
  clinic_location_id: string;
  start_time_utc: string;
  end_time_utc: string;
}

export interface BookingRead {
  id: string;
  patient_profile_id: string;
  doctor_id: string;
  clinic_location_id: string;
  start_time_utc: string;
  end_time_utc: string;
  status: BookingStatus;
  source: BookingSource;
  fee_charged: number;
  address_snapshot: string;
  expires_at: string | null;
  rescheduled_from_id: string | null;
  cancelled_by: CancelledBy | null;
  cancelled_reason: string | null;
  rejected_reason: string | null;
  confirmed_at: string | null;
  cancelled_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
