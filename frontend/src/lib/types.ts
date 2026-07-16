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
  average_rating: number | null;
  review_count: number;
}

export interface DoctorSearchResult {
  id: string;
  full_name: string;
  specialization: SpecializationRead;
  consultation_fee: number;
  cities: string[];
  photo_url: string | null;
  next_available_slot_utc: string | null;
  average_rating: number | null;
  review_count: number;
}

export type DoctorSortOrder = "name" | "fee_asc" | "fee_desc";

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

export interface PatientNoteRead {
  id: string;
  booking_id: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface ClinicalNoteRead {
  id: string;
  booking_id: string;
  content: string;
  is_shared_with_patient: boolean;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export type ReviewModerationStatus = "pending" | "approved" | "rejected";

export interface ReviewRead {
  id: string;
  booking_id: string;
  doctor_id: string;
  patient_profile_id: string;
  rating: number;
  comment: string | null;
  moderation_status: ReviewModerationStatus;
  moderation_reason: string | null;
  doctor_reply: string | null;
  doctor_replied_at: string | null;
  created_at: string;
}

export type NotificationChannel = "in_app" | "email" | "sms";
export type NotificationStatus = "pending" | "sent" | "failed";

export interface NotificationRead {
  id: string;
  booking_id: string | null;
  channel: NotificationChannel;
  status: NotificationStatus;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface UnreadCountRead {
  unread_count: number;
}

export interface DoctorDashboardRead {
  today: BookingRead[];
  upcoming: BookingRead[];
  pending: BookingRead[];
}

export interface DoctorVerificationQueueItem {
  id: string;
  user_id: string;
  full_name: string;
  email: string;
  pmc_number: string;
  specialization_id: string;
  verification_status: DoctorVerificationStatus;
}

export interface PlatformStatsRead {
  patients: number;
  doctors: number;
  doctors_unverified: number;
  doctors_verified: number;
  doctors_rejected: number;
  bookings_by_status: Record<string, number>;
  pending_reviews: number;
  approved_reviews: number;
}

// --- F17: multi-agent assistant ---------------------------------------

export type AgentRole = "user" | "assistant" | "system" | "tool";

export interface ChatSessionRead {
  id: string;
  active_patient_profile_id: string | null;
  created_at: string;
  last_activity_at: string;
}

export interface ChatMessageRead {
  id: string;
  role: AgentRole;
  content: string;
  agent_name: string | null;
  created_at: string;
}

export interface ChatMessageResponse {
  reply: string;
  draft_booking: BookingRead | null;
  emergency: boolean;
}

// --- F20: waitlist -------------------------------------------------------

export type WaitlistStatus = "waiting" | "holding" | "expired" | "booked" | "cancelled";

export interface WaitlistRead {
  id: string;
  doctor_id: string;
  clinic_location_id: string;
  start_time_utc: string;
  end_time_utc: string;
  position: number;
  status: WaitlistStatus;
  hold_booking_id: string | null;
  joined_at: string;
}

// --- F20: follow-up --------------------------------------------------------

export type FollowUpStatus = "scheduled" | "notified" | "deferred";

export interface FollowUpRead {
  id: string;
  booking_id: string;
  doctor_id: string;
  patient_profile_id: string;
  weeks: number;
  target_date: string;
  status: FollowUpStatus;
  created_at: string;
}

// --- F20: AI visit summary --------------------------------------------------

export interface VisitSummaryDraft {
  chief_complaint: string;
  assessment: string;
  plan: string;
}

// --- F20: family accounts -----------------------------------------------

export interface PatientProfileRead {
  id: string;
  user_id: string;
  full_name: string;
  relationship_label: string;
  date_of_birth: string | null;
  is_active: boolean;
  created_at: string;
}
