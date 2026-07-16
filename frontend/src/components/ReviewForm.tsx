"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ReviewRead } from "@/lib/types";

const STARS = [1, 2, 3, 4, 5];

/** Review submission for a completed booking (F11) — one review per booking,
 * so this checks for an existing review first and shows it read-only. */
export function ReviewForm({ bookingId }: { bookingId: string }) {
  const [existing, setExisting] = useState<ReviewRead | null | undefined>(undefined);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ReviewRead | null>(`/api/v1/bookings/${bookingId}/review`)
      .then(setExisting)
      .catch(() => setExisting(null));
  }, [bookingId]);

  async function handleSubmit() {
    if (rating === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const review = await api.post<ReviewRead>(`/api/v1/bookings/${bookingId}/review`, {
        rating,
        comment: comment.trim() || null,
      });
      setExisting(review);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit review.");
    } finally {
      setSubmitting(false);
    }
  }

  if (existing === undefined) return null;

  if (existing) {
    return (
      <div className="mt-2 rounded-md bg-slate-50 p-2 text-sm text-slate-600">
        <span className="font-medium text-slate-700">Your review: </span>★ {existing.rating}/5
        {existing.comment && <p className="mt-1">{existing.comment}</p>}
        {existing.moderation_status === "pending" && (
          <p className="mt-1 text-xs text-slate-400">Awaiting moderation before it&apos;s shown publicly.</p>
        )}
        {existing.doctor_reply && (
          <p className="mt-2 rounded-md bg-white p-2">
            <span className="font-medium">Doctor&apos;s reply: </span>
            {existing.doctor_reply}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-1 rounded-md bg-slate-50 p-2">
      <div className="flex items-center gap-1">
        {STARS.map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => setRating(star)}
            className={`text-lg ${star <= rating ? "text-amber-500" : "text-slate-300"}`}
            aria-label={`${star} star${star > 1 ? "s" : ""}`}
          >
            ★
          </button>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Share your experience (optional)"
        rows={2}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
      <button
        onClick={handleSubmit}
        disabled={submitting || rating === 0}
        className="w-fit rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
      >
        {submitting ? "Submitting…" : "Submit review"}
      </button>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
