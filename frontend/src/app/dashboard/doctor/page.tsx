"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { BookingRead, ClinicLocationRead, DoctorProfileRead, Page, Weekday } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { ClinicalNoteEditor, MedicalHistoryViewer, PatientNoteViewer } from "@/components/NoteWidgets";
import { AIDraftHelper, FollowUpForm } from "@/components/DoctorSmartTools";

const WEEKDAYS: { value: Weekday; label: string }[] = [
  { value: "mon", label: "Monday" },
  { value: "tue", label: "Tuesday" },
  { value: "wed", label: "Wednesday" },
  { value: "thu", label: "Thursday" },
  { value: "fri", label: "Friday" },
  { value: "sat", label: "Saturday" },
  { value: "sun", label: "Sunday" },
];

export default function DoctorDashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const [profile, setProfile] = useState<DoctorProfileRead | null>(null);
  const [bookings, setBookings] = useState<BookingRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [aiDrafts, setAiDrafts] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const [profileRes, bookingsRes] = await Promise.all([
      api.get<DoctorProfileRead>("/api/v1/doctors/me"),
      api.get<Page<BookingRead>>("/api/v1/bookings/doctor/me?page=1&page_size=50"),
    ]);
    setProfile(profileRes);
    setBookings(bookingsRes.items);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!user) return;
    load();
  }, [user, load]);

  async function handleAccept(id: string) {
    setActionError(null);
    setBusyId(id);
    try {
      await api.post(`/api/v1/bookings/${id}/accept`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not accept this booking.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(id: string) {
    const reason = window.prompt("Reason for declining?");
    if (!reason) return;
    setActionError(null);
    setBusyId(id);
    try {
      await api.post(`/api/v1/bookings/${id}/reject`, { reason });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not decline this booking.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleCancel(id: string) {
    const reason = window.prompt("Reason for cancelling?");
    if (!reason) return;
    setActionError(null);
    setBusyId(id);
    try {
      await api.post(`/api/v1/bookings/${id}/doctor-cancel`, { reason });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not cancel this booking.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleComplete(id: string) {
    setActionError(null);
    setBusyId(id);
    try {
      await api.post(`/api/v1/bookings/${id}/complete`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not mark this booking completed.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleNoShow(id: string) {
    setActionError(null);
    setBusyId(id);
    try {
      await api.post(`/api/v1/bookings/${id}/no-show`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not mark this booking as a no-show.");
    } finally {
      setBusyId(null);
    }
  }

  if (authLoading || loading || !profile) {
    return <p className="text-slate-500">Loading…</p>;
  }

  const pending = bookings.filter((b) => b.status === "pending");
  const others = bookings.filter((b) => b.status !== "pending");

  return (
    <div className="flex flex-col gap-8">
      {profile.verification_status !== "verified" && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Your account is <strong>{profile.verification_status}</strong>. You won&apos;t appear in
          search or receive bookings until an admin verifies your PMC number.
        </div>
      )}

      {actionError && <p className="text-sm text-red-600">{actionError}</p>}

      <section>
        <h1 className="mb-4 text-2xl font-semibold">Pending requests</h1>
        {pending.length === 0 && <p className="text-slate-500">No pending requests.</p>}
        <div className="flex flex-col gap-3">
          {pending.map((booking) => (
            <div key={booking.id} className="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <div className="mb-2 flex items-center gap-2">
                <StatusBadge status={booking.status} />
              </div>
              <p className="font-medium">{new Date(booking.start_time_utc).toLocaleString()}</p>
              <p className="text-sm text-slate-600">{booking.address_snapshot}</p>
              <p className="text-sm text-slate-600">Fee: Rs. {booking.fee_charged}</p>
              <PatientNoteViewer bookingId={booking.id} />
              <MedicalHistoryViewer bookingId={booking.id} />
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => handleAccept(booking.id)}
                  disabled={busyId === booking.id}
                  className="rounded-md bg-teal-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
                >
                  Accept
                </button>
                <button
                  onClick={() => handleReject(booking.id)}
                  disabled={busyId === booking.id}
                  className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  Decline
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold">All appointments</h2>
        <div className="flex flex-col gap-3">
          {others.map((booking) => (
            <div
              key={booking.id}
              className="flex flex-col justify-between gap-2 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-center"
            >
              <div>
                <div className="mb-1">
                  <StatusBadge status={booking.status} />
                </div>
                <p className="font-medium">{new Date(booking.start_time_utc).toLocaleString()}</p>
                <p className="text-sm text-slate-500">{booking.address_snapshot}</p>
                <PatientNoteViewer bookingId={booking.id} />
                {(booking.status === "pending" ||
                  booking.status === "confirmed" ||
                  booking.status === "completed") && <MedicalHistoryViewer bookingId={booking.id} />}
                {(booking.status === "confirmed" || booking.status === "completed") && (
                  <>
                    <ClinicalNoteEditor
                      key={aiDrafts[booking.id] ?? `note-${booking.id}`}
                      bookingId={booking.id}
                      prefill={aiDrafts[booking.id]}
                    />
                    <AIDraftHelper
                      bookingId={booking.id}
                      onDraft={(text) => setAiDrafts((prev) => ({ ...prev, [booking.id]: text }))}
                    />
                    <FollowUpForm bookingId={booking.id} />
                  </>
                )}
              </div>
              {booking.status === "confirmed" && (
                <div className="flex shrink-0 gap-2">
                  <button
                    onClick={() => handleComplete(booking.id)}
                    disabled={busyId === booking.id}
                    className="rounded-md border border-teal-300 px-3 py-1.5 text-sm text-teal-700 hover:bg-teal-50 disabled:opacity-60"
                  >
                    Mark completed
                  </button>
                  <button
                    onClick={() => handleNoShow(booking.id)}
                    disabled={busyId === booking.id}
                    className="rounded-md border border-orange-300 px-3 py-1.5 text-sm text-orange-700 hover:bg-orange-50 disabled:opacity-60"
                  >
                    No-show
                  </button>
                  <button
                    onClick={() => handleCancel(booking.id)}
                    disabled={busyId === booking.id}
                    className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <ClinicSetup profile={profile} onChange={load} />
    </div>
  );
}

function ClinicSetup({ profile, onChange }: { profile: DoctorProfileRead; onChange: () => void }) {
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [clinicError, setClinicError] = useState<string | null>(null);
  const [submittingClinic, setSubmittingClinic] = useState(false);

  const [ruleClinicId, setRuleClinicId] = useState(profile.clinic_locations[0]?.id ?? "");
  const [weekday, setWeekday] = useState<Weekday>("mon");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("17:00");
  const [slotMinutes, setSlotMinutes] = useState(30);
  const [ruleError, setRuleError] = useState<string | null>(null);
  const [submittingRule, setSubmittingRule] = useState(false);

  async function handleAddClinic(e: React.FormEvent) {
    e.preventDefault();
    setClinicError(null);
    setSubmittingClinic(true);
    try {
      await api.post<ClinicLocationRead>("/api/v1/doctors/me/clinics", { name, address, city });
      setName("");
      setAddress("");
      setCity("");
      onChange();
    } catch (err) {
      setClinicError(err instanceof ApiError ? err.message : "Could not add clinic.");
    } finally {
      setSubmittingClinic(false);
    }
  }

  async function handleAddRule(e: React.FormEvent) {
    e.preventDefault();
    if (!ruleClinicId) {
      setRuleError("Add a clinic first.");
      return;
    }
    setRuleError(null);
    setSubmittingRule(true);
    try {
      await api.post("/api/v1/doctors/me/availability-rules", {
        clinic_location_id: ruleClinicId,
        weekday,
        start_time_local: `${startTime}:00`,
        end_time_local: `${endTime}:00`,
        slot_duration_minutes: slotMinutes,
      });
      onChange();
    } catch (err) {
      setRuleError(err instanceof ApiError ? err.message : "Could not add availability.");
    } finally {
      setSubmittingRule(false);
    }
  }

  return (
    <section className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Clinics &amp; availability</h2>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-3 font-medium">Your clinics</h3>
        {profile.clinic_locations.length === 0 && (
          <p className="mb-3 text-sm text-slate-500">No clinics yet — add one below.</p>
        )}
        <ul className="mb-4 flex flex-col gap-2 text-sm text-slate-600">
          {profile.clinic_locations.map((c) => (
            <ClinicRow key={c.id} clinic={c} onChange={onChange} />
          ))}
        </ul>
        <form onSubmit={handleAddClinic} className="grid gap-2 sm:grid-cols-4">
          <input
            placeholder="Clinic name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            placeholder="Address"
            required
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            placeholder="City"
            required
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={submittingClinic}
            className="rounded-md bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
          >
            Add clinic
          </button>
        </form>
        {clinicError && <p className="mt-2 text-sm text-red-600">{clinicError}</p>}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-3 font-medium">Weekly availability</h3>
        <form onSubmit={handleAddRule} className="grid gap-2 sm:grid-cols-5">
          <select
            value={ruleClinicId}
            onChange={(e) => setRuleClinicId(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {profile.clinic_locations.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={weekday}
            onChange={(e) => setWeekday(e.target.value as Weekday)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {WEEKDAYS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
          <input
            type="time"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="time"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <select
            value={slotMinutes}
            onChange={(e) => setSlotMinutes(Number(e.target.value))}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {[15, 30, 45, 60].map((m) => (
              <option key={m} value={m}>
                {m} min
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={submittingRule}
            className="rounded-md bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
          >
            Add availability
          </button>
        </form>
        {ruleError && <p className="mt-2 text-sm text-red-600">{ruleError}</p>}
      </div>
    </section>
  );
}

function ClinicRow({ clinic, onChange }: { clinic: ClinicLocationRead; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [address, setAddress] = useState(clinic.address);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.patch<ClinicLocationRead>(`/api/v1/doctors/me/clinics/${clinic.id}`, { address });
      setEditing(false);
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update address.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <li className="flex items-center justify-between gap-2">
        <span>
          {clinic.name} — {clinic.address}, {clinic.city}
        </span>
        <button onClick={() => setEditing(true)} className="text-xs text-teal-700 underline">
          edit address
        </button>
      </li>
    );
  }

  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm"
        />
        <button
          onClick={handleSave}
          disabled={saving || !address.trim()}
          className="rounded-md bg-teal-600 px-2 py-1 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button onClick={() => setEditing(false)} className="text-xs text-slate-500 underline">
          cancel
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </li>
  );
}
