"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type {
  DoctorVerificationQueueItem,
  Page,
  PlatformStatsRead,
  ReviewRead,
} from "@/lib/types";

export default function AdminDashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const [stats, setStats] = useState<PlatformStatsRead | null>(null);
  const [pendingDoctors, setPendingDoctors] = useState<DoctorVerificationQueueItem[]>([]);
  const [pendingReviews, setPendingReviews] = useState<ReviewRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [statsRes, doctorsRes, reviewsRes] = await Promise.all([
      api.get<PlatformStatsRead>("/api/v1/admin/stats"),
      api.get<Page<DoctorVerificationQueueItem>>("/api/v1/admin/doctors/pending?page=1&page_size=50"),
      api.get<Page<ReviewRead>>("/api/v1/admin/reviews/pending?page=1&page_size=50"),
    ]);
    setStats(statsRes);
    setPendingDoctors(doctorsRes.items);
    setPendingReviews(reviewsRes.items);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!user || user.role !== "admin") return;
    load();
  }, [user, load]);

  async function handleVerify(doctorId: string, status: "verified" | "rejected") {
    const reason = status === "rejected" ? window.prompt("Reason for rejection?") : null;
    if (status === "rejected" && !reason) return;
    setActionError(null);
    setBusyId(doctorId);
    try {
      await api.post(`/api/v1/admin/doctors/${doctorId}/verify`, { status, reason });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not update verification status.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleModerate(reviewId: string, status: "approved" | "rejected") {
    setActionError(null);
    setBusyId(reviewId);
    try {
      await api.post(`/api/v1/admin/reviews/${reviewId}/moderate`, { status });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not moderate this review.");
    } finally {
      setBusyId(null);
    }
  }

  if (authLoading || loading) {
    return <p className="text-slate-500">Loading…</p>;
  }

  if (!user || user.role !== "admin") {
    return <p className="text-slate-500">You don&apos;t have access to this page.</p>;
  }

  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-2xl font-semibold">Admin dashboard</h1>
      {actionError && <p className="text-sm text-red-600">{actionError}</p>}

      {stats && (
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile label="Patients" value={stats.patients} />
          <StatTile label="Doctors (verified)" value={stats.doctors_verified} />
          <StatTile label="Doctors (unverified)" value={stats.doctors_unverified} />
          <StatTile label="Pending reviews" value={stats.pending_reviews} />
        </section>
      )}

      <section>
        <h2 className="mb-4 text-xl font-semibold">Doctor verification queue</h2>
        {pendingDoctors.length === 0 && <p className="text-slate-500">Nothing pending.</p>}
        <div className="flex flex-col gap-3">
          {pendingDoctors.map((doctor) => (
            <div
              key={doctor.id}
              className="flex flex-col justify-between gap-2 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-center"
            >
              <div>
                <p className="font-medium">{doctor.full_name}</p>
                <p className="text-sm text-slate-500">{doctor.email}</p>
                <p className="text-sm text-slate-500">PMC: {doctor.pmc_number}</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleVerify(doctor.id, "verified")}
                  disabled={busyId === doctor.id}
                  className="rounded-md bg-teal-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
                >
                  Approve
                </button>
                <button
                  onClick={() => handleVerify(doctor.id, "rejected")}
                  disabled={busyId === doctor.id}
                  className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold">Review moderation queue</h2>
        {pendingReviews.length === 0 && <p className="text-slate-500">Nothing pending.</p>}
        <div className="flex flex-col gap-3">
          {pendingReviews.map((review) => (
            <div key={review.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <p className="font-medium">Rating: {review.rating} / 5</p>
              {review.comment && <p className="mt-1 text-sm text-slate-600">{review.comment}</p>}
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => handleModerate(review.id, "approved")}
                  disabled={busyId === review.id}
                  className="rounded-md bg-teal-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
                >
                  Approve
                </button>
                <button
                  onClick={() => handleModerate(review.id, "rejected")}
                  disabled={busyId === review.id}
                  className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-2xl font-semibold text-slate-900">{value}</p>
      <p className="text-sm text-slate-500">{label}</p>
    </div>
  );
}
