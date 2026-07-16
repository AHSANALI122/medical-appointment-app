"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { WaitlistRead } from "@/lib/types";

const STYLES: Record<WaitlistRead["status"], string> = {
  waiting: "bg-slate-100 text-slate-700",
  holding: "bg-amber-100 text-amber-800",
  expired: "bg-slate-100 text-slate-500",
  booked: "bg-teal-100 text-teal-800",
  cancelled: "bg-red-100 text-red-700",
};

/** F20 — status UI for the patient's waitlist entries (F20 acceptance:
 * "waitlist hold expiry tested"). Joining happens automatically when a
 * `book this slot` attempt finds it already held is out of this widget's
 * scope for now — this covers viewing status and leaving a waiting entry. */
export function WaitlistPanel() {
  const [entries, setEntries] = useState<WaitlistRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get<WaitlistRead[]>("/api/v1/waitlist/me");
      setEntries(res);
    } catch (err) {
      // Feature-flagged (F20) — a 403 here just means it's disabled; don't
      // surface that as an error on a dashboard section most patients
      // won't have entries in anyway.
      if (!(err instanceof ApiError && err.status === 403)) {
        setError(err instanceof ApiError ? err.message : "Could not load your waitlist.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleLeave(id: string) {
    setBusyId(id);
    try {
      await api.delete<WaitlistRead>(`/api/v1/waitlist/${id}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not leave the waitlist.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading || entries.length === 0) return null;

  return (
    <section>
      <h2 className="mb-4 text-xl font-semibold">Waitlist</h2>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      <div className="flex flex-col gap-3">
        {entries.map((entry) => (
          <div
            key={entry.id}
            className="flex flex-col justify-between gap-2 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-center"
          >
            <div>
              <span className={`mb-1 inline-block rounded-full px-2.5 py-1 text-xs font-medium ${STYLES[entry.status]}`}>
                {entry.status}
              </span>
              <p className="font-medium text-slate-900">{new Date(entry.start_time_utc).toLocaleString()}</p>
              <p className="text-sm text-slate-500">Position #{entry.position} in line</p>
              {entry.status === "holding" && (
                <p className="text-sm text-teal-700">
                  A slot opened up — check your bookings above to confirm before the hold expires.
                </p>
              )}
            </div>
            {entry.status === "waiting" && (
              <button
                onClick={() => handleLeave(entry.id)}
                disabled={busyId === entry.id}
                className="shrink-0 rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
              >
                {busyId === entry.id ? "Leaving…" : "Leave waitlist"}
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
