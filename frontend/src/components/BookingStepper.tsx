"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { BookingRead, ClinicLocationRead, DoctorProfileRead, Page, ReviewRead, SlotRead } from "@/lib/types";
import { Countdown } from "@/components/Countdown";
import { useFamilyProfiles } from "@/components/FamilyProfiles";

type Step = "slot" | "review" | "draft" | "confirmed";

const stepVariants = {
  enter: { opacity: 0, x: 24 },
  center: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -24 },
};

export function BookingStepper({ doctorId }: { doctorId: string }) {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  const [doctor, setDoctor] = useState<DoctorProfileRead | null>(null);
  const [doctorError, setDoctorError] = useState<string | null>(null);
  const [clinicId, setClinicId] = useState<string>("");
  const [slots, setSlots] = useState<SlotRead[]>([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<SlotRead | null>(null);

  const [step, setStep] = useState<Step>("slot");
  const [draft, setDraft] = useState<BookingRead | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const familyProfiles = useFamilyProfiles();
  const [bookingForProfileId, setBookingForProfileId] = useState<string>("");

  useEffect(() => {
    api
      .get<DoctorProfileRead>(`/api/v1/doctors/${doctorId}`)
      .then((d) => {
        setDoctor(d);
        if (d.clinic_locations.length > 0) setClinicId(d.clinic_locations[0].id);
      })
      .catch((err) => setDoctorError(err instanceof ApiError ? err.message : "Doctor not found."));
  }, [doctorId]);

  useEffect(() => {
    if (!clinicId) return;
    setSlotsLoading(true);
    api
      .get<SlotRead[]>(`/api/v1/doctors/${doctorId}/slots?clinic_location_id=${clinicId}`)
      .then(setSlots)
      .finally(() => setSlotsLoading(false));
  }, [doctorId, clinicId]);

  const slotsByDate = useMemo(() => {
    const grouped = new Map<string, SlotRead[]>();
    for (const slot of slots) {
      const dateKey = new Date(slot.start_time_utc).toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      });
      const existing = grouped.get(dateKey) ?? [];
      existing.push(slot);
      grouped.set(dateKey, existing);
    }
    return grouped;
  }, [slots]);

  const selectedClinic: ClinicLocationRead | undefined = doctor?.clinic_locations.find(
    (c) => c.id === clinicId,
  );

  async function handleCreateDraft() {
    if (!selectedSlot) return;
    setActionError(null);
    setSubmitting(true);
    try {
      const booking = await api.post<BookingRead>("/api/v1/bookings", {
        doctor_id: doctorId,
        clinic_location_id: selectedSlot.clinic_location_id,
        start_time_utc: selectedSlot.start_time_utc,
        end_time_utc: selectedSlot.end_time_utc,
        patient_profile_id: bookingForProfileId || undefined,
      });
      setDraft(booking);
      setStep("draft");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not hold this slot.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirm() {
    if (!draft) return;
    setActionError(null);
    setSubmitting(true);
    try {
      const confirmed = await api.post<BookingRead>(`/api/v1/bookings/${draft.id}/confirm`);
      setDraft(confirmed);
      setStep("confirmed");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not confirm this booking.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleDraftExpired() {
    setActionError("This hold expired. Please pick a slot again.");
    setDraft(null);
    setSelectedSlot(null);
    setStep("slot");
  }

  if (doctorError) {
    return <p className="text-red-600">{doctorError}</p>;
  }

  if (!doctor) {
    return <p className="text-slate-500">Loading…</p>;
  }

  return (
    <div>
      <div className="mb-8 rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{doctor.full_name}</h1>
            <p className="text-slate-600">{doctor.specialization.name_en}</p>
            {doctor.qualifications && <p className="mt-1 text-sm text-slate-500">{doctor.qualifications}</p>}
          </div>
          <div className="text-right">
            <p className="text-xl font-semibold text-teal-700">Rs. {doctor.consultation_fee}</p>
            {doctor.verification_status === "verified" ? (
              <span className="text-xs text-teal-700">✓ PMC Verified</span>
            ) : (
              <span className="text-xs text-amber-600">Verification pending</span>
            )}
            {doctor.review_count > 0 && (
              <p className="mt-1 text-sm text-slate-600">
                ★ {doctor.average_rating?.toFixed(1)}{" "}
                <span className="text-slate-400">({doctor.review_count} reviews)</span>
              </p>
            )}
          </div>
        </div>
        {doctor.bio && <p className="mt-4 text-sm text-slate-600">{doctor.bio}</p>}
      </div>

      <DoctorReviews doctorId={doctorId} />

      {doctor.verification_status !== "verified" ? (
        <p className="text-slate-500">This doctor is not currently accepting bookings.</p>
      ) : authLoading ? null : !user ? (
        <div className="rounded-md border border-slate-200 bg-white p-6 text-center">
          <p className="mb-3 text-slate-700">Log in as a patient to book an appointment.</p>
          <Link href={`/login?next=/doctors/${doctorId}`} className="text-teal-700 hover:underline">
            Log in
          </Link>
        </div>
      ) : user.role !== "patient" ? (
        <p className="text-slate-500">Only patient accounts can book appointments.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white p-6">
          <AnimatePresence mode="wait">
            {step === "slot" && (
              <motion.div
                key="slot"
                variants={stepVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.2 }}
              >
                <h2 className="mb-4 text-lg font-semibold">1. Choose a slot</h2>
                {doctor.clinic_locations.length > 1 && (
                  <select
                    value={clinicId}
                    onChange={(e) => setClinicId(e.target.value)}
                    className="mb-4 rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    {doctor.clinic_locations.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} — {c.city}
                      </option>
                    ))}
                  </select>
                )}
                {slotsLoading && <p className="text-slate-500">Loading slots…</p>}
                {!slotsLoading && slots.length === 0 && (
                  <p className="text-slate-500">No available slots in the next two weeks.</p>
                )}
                <div className="flex flex-col gap-4">
                  {Array.from(slotsByDate.entries()).map(([date, daySlots]) => (
                    <div key={date}>
                      <p className="mb-2 text-sm font-medium text-slate-700">{date}</p>
                      <div className="flex flex-wrap gap-2">
                        {daySlots.map((slot) => (
                          <button
                            key={slot.start_time_utc}
                            onClick={() => {
                              setSelectedSlot(slot);
                              setStep("review");
                            }}
                            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:border-teal-500 hover:bg-teal-50"
                          >
                            {new Date(slot.start_time_utc).toLocaleTimeString(undefined, {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {step === "review" && selectedSlot && selectedClinic && (
              <motion.div
                key="review"
                variants={stepVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.2 }}
              >
                <h2 className="mb-4 text-lg font-semibold">2. Review</h2>
                <dl className="mb-6 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Doctor</dt>
                    <dd className="font-medium">{doctor.full_name}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Time</dt>
                    <dd className="font-medium">
                      {new Date(selectedSlot.start_time_utc).toLocaleString()}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Location</dt>
                    <dd className="font-medium">
                      {selectedClinic.name}, {selectedClinic.address}, {selectedClinic.city}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Fee</dt>
                    <dd className="font-medium text-teal-700">Rs. {doctor.consultation_fee}</dd>
                  </div>
                </dl>
                {familyProfiles.length > 1 && (
                  <div className="mb-4">
                    <label className="mb-1 block text-sm text-slate-500">Booking for</label>
                    <select
                      value={bookingForProfileId}
                      onChange={(e) => setBookingForProfileId(e.target.value)}
                      className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                    >
                      {familyProfiles.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.relationship_label === "self" ? "Myself" : `${p.full_name} (${p.relationship_label})`}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {actionError && <p className="mb-3 text-sm text-red-600">{actionError}</p>}
                <div className="flex gap-3">
                  <button
                    onClick={() => setStep("slot")}
                    className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
                  >
                    Back
                  </button>
                  <button
                    onClick={handleCreateDraft}
                    disabled={submitting}
                    className="rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
                  >
                    {submitting ? "Holding slot…" : "Hold this slot"}
                  </button>
                </div>
              </motion.div>
            )}

            {step === "draft" && draft && (
              <motion.div
                key="draft"
                variants={stepVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.2 }}
              >
                <h2 className="mb-4 text-lg font-semibold">3. Confirm your appointment</h2>
                <div className="mb-4 rounded-md bg-amber-50 border border-amber-200 p-4">
                  <p className="text-sm text-amber-900">
                    This slot is held for you. Confirm within{" "}
                    {draft.expires_at && (
                      <Countdown expiresAt={draft.expires_at} onExpire={handleDraftExpired} />
                    )}{" "}
                    or it will be released.
                  </p>
                </div>
                <dl className="mb-6 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Time</dt>
                    <dd className="font-medium">{new Date(draft.start_time_utc).toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Location</dt>
                    <dd className="font-medium">{draft.address_snapshot}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Fee</dt>
                    <dd className="font-medium text-teal-700">Rs. {draft.fee_charged}</dd>
                  </div>
                </dl>
                {actionError && <p className="mb-3 text-sm text-red-600">{actionError}</p>}
                <button
                  onClick={handleConfirm}
                  disabled={submitting}
                  className="w-full rounded-md bg-teal-600 px-4 py-3 font-medium text-white hover:bg-teal-700 disabled:opacity-60"
                >
                  {submitting ? "Confirming…" : "Confirm appointment"}
                </button>
              </motion.div>
            )}

            {step === "confirmed" && draft && (
              <motion.div
                key="confirmed"
                variants={stepVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.2 }}
                className="text-center"
              >
                <h2 className="mb-2 text-lg font-semibold text-teal-700">Request sent!</h2>
                <p className="mb-6 text-sm text-slate-600">
                  Your appointment request has been sent to the doctor. You&apos;ll be notified once
                  they respond.
                </p>
                <button
                  onClick={() => router.push("/dashboard/patient")}
                  className="rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700"
                >
                  Go to my bookings
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

function DoctorReviews({ doctorId }: { doctorId: string }) {
  const [reviews, setReviews] = useState<ReviewRead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Page<ReviewRead>>(`/api/v1/doctors/${doctorId}/reviews?page=1&page_size=10`)
      .then((res) => setReviews(res.items))
      .finally(() => setLoading(false));
  }, [doctorId]);

  if (loading || reviews.length === 0) return null;

  return (
    <div className="mb-8 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="mb-4 text-lg font-semibold">Patient reviews</h2>
      <div className="flex flex-col gap-4">
        {reviews.map((review) => (
          <div key={review.id} className="border-b border-slate-100 pb-4 last:border-0 last:pb-0">
            <p className="font-medium">★ {review.rating} / 5</p>
            {review.comment && <p className="mt-1 text-sm text-slate-600">{review.comment}</p>}
            {review.doctor_reply && (
              <p className="mt-2 rounded-md bg-slate-50 p-2 text-sm text-slate-600">
                <span className="font-medium">Doctor&apos;s reply: </span>
                {review.doctor_reply}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
