"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { BookingRead, Page } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { Countdown } from "@/components/Countdown";
import { ClinicalNoteViewer, PatientNoteEditor } from "@/components/NoteWidgets";
import { ReviewForm } from "@/components/ReviewForm";
import { FamilyProfiles } from "@/components/FamilyProfiles";
import { WaitlistPanel } from "@/components/WaitlistPanel";
import { MedicalHistoryPanel } from "@/components/MedicalHistoryPanel";
import { NotificationPreferenceToggle } from "@/components/NotificationPreferenceToggle";

const CANCELLABLE: BookingRead["status"][] = ["pending", "confirmed"];

export default function PatientDashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const [bookings, setBookings] = useState<BookingRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const loadBookings = useCallback(async () => {
    try {
      const page = await api.get<Page<BookingRead>>("/api/v1/bookings/me?page=1&page_size=50");
      setBookings(page.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    loadBookings();
  }, [user, loadBookings]);

  // Live updates: prefer SSE, fall back to polling if the stream errors out.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!user) return;

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(loadBookings, 3000);
    };

    let source: EventSource | null = null;
    try {
      source = new EventSource(apiUrl("/api/v1/bookings/me/stream"), { withCredentials: true });
      source.onmessage = () => loadBookings();
      source.onerror = () => {
        source?.close();
        startPolling();
      };
    } catch {
      startPolling();
    }

    return () => {
      source?.close();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [user, loadBookings]);

  async function handleCancel(bookingId: string) {
    const reason = window.prompt("Reason for cancelling?");
    if (!reason) return;
    setActionError(null);
    setCancellingId(bookingId);
    try {
      await api.post<BookingRead>(`/api/v1/bookings/${bookingId}/cancel`, { reason });
      await loadBookings();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not cancel this booking.");
    } finally {
      setCancellingId(null);
    }
  }

  async function handleConfirmDraft(bookingId: string) {
    setActionError(null);
    setCancellingId(bookingId);
    try {
      await api.post<BookingRead>(`/api/v1/bookings/${bookingId}/confirm`);
      await loadBookings();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not confirm this booking.");
    } finally {
      setCancellingId(null);
    }
  }

  if (authLoading || loading) {
    return <p className="text-slate-500">Loading…</p>;
  }

  if (!user) {
    return <p className="text-slate-500">Please log in.</p>;
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">My bookings</h1>
      {actionError && <p className="mb-4 text-sm text-red-600">{actionError}</p>}
      {bookings.length === 0 && <p className="text-slate-500">You have no bookings yet.</p>}
      <div className="flex flex-col gap-3">
        {bookings.map((booking) => (
          <div
            key={booking.id}
            className="flex flex-col justify-between gap-2 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-center"
          >
            <div>
              <div className="mb-1 flex items-center gap-2">
                <StatusBadge status={booking.status} />
                {booking.status === "pending" && booking.expires_at && (
                  <span className="text-xs text-slate-400">
                    doctor must respond by {new Date(booking.expires_at).toLocaleString()}
                  </span>
                )}
                {booking.status === "draft" && booking.expires_at && (
                  <span className="text-xs text-amber-700">
                    hold expires in <Countdown expiresAt={booking.expires_at} onExpire={loadBookings} />
                  </span>
                )}
                {booking.source === "system_waitlist" && (
                  <span className="text-xs text-teal-700">from waitlist</span>
                )}
              </div>
              <p className="font-medium text-slate-900">
                {new Date(booking.start_time_utc).toLocaleString()}
              </p>
              <p className="text-sm text-slate-500">{booking.address_snapshot}</p>
              <p className="text-sm text-slate-500">Fee: Rs. {booking.fee_charged}</p>
              {booking.status === "draft" && (
                <button
                  onClick={() => handleConfirmDraft(booking.id)}
                  disabled={cancellingId === booking.id}
                  className="mt-2 rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
                >
                  {cancellingId === booking.id ? "Confirming…" : "Confirm appointment"}
                </button>
              )}
              {booking.status === "rejected" && booking.rejected_reason && (
                <p className="mt-1 text-sm text-red-600">Reason: {booking.rejected_reason}</p>
              )}
              {booking.status === "cancelled" && booking.cancelled_reason && (
                <p className="mt-1 text-sm text-red-600">
                  Cancelled by {booking.cancelled_by}: {booking.cancelled_reason}
                </p>
              )}
              <PatientNoteEditor bookingId={booking.id} />
              {(booking.status === "confirmed" || booking.status === "completed") && (
                <ClinicalNoteViewer bookingId={booking.id} />
              )}
              {booking.status === "completed" && <ReviewForm bookingId={booking.id} />}
            </div>
            {CANCELLABLE.includes(booking.status) && (
              <button
                onClick={() => handleCancel(booking.id)}
                disabled={cancellingId === booking.id}
                className="shrink-0 rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
              >
                {cancellingId === booking.id ? "Cancelling…" : "Cancel"}
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="mt-10 flex flex-col gap-8">
        <WaitlistPanel />
        <FamilyProfiles />
        <MedicalHistoryPanel />
        <NotificationPreferenceToggle />
      </div>
    </div>
  );
}
