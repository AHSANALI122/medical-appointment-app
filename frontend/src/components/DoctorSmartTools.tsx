"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { FollowUpRead, VisitSummaryDraft } from "@/lib/types";

/** F20 AI visit summary — HITL: generates a draft only, never saves.
 * `onDraft` hands the formatted text to the adjacent ClinicalNoteEditor,
 * which the doctor still has to review and save themselves. */
export function AIDraftHelper({ bookingId, onDraft }: { bookingId: string; onDraft: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [roughNotes, setRoughNotes] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const draft = await api.post<VisitSummaryDraft>(
        `/api/v1/bookings/${bookingId}/clinical-note/ai-draft`,
        { rough_notes: roughNotes },
      );
      onDraft(`Chief complaint: ${draft.chief_complaint}\nAssessment: ${draft.assessment}\nPlan: ${draft.plan}`);
      setOpen(false);
      setRoughNotes("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate a draft.");
    } finally {
      setGenerating(false);
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="mt-1 text-xs text-teal-700 underline">
        AI draft from rough notes
      </button>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-1 rounded-md border border-slate-200 bg-white p-2">
      <textarea
        value={roughNotes}
        onChange={(e) => setRoughNotes(e.target.value)}
        placeholder="Rough notes from the visit — turned into a structured draft you can edit before saving"
        rows={2}
        className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={handleGenerate}
          disabled={generating || !roughNotes.trim()}
          className="rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {generating ? "Generating…" : "Generate draft"}
        </button>
        <button onClick={() => setOpen(false)} className="text-xs text-slate-500 underline">
          cancel
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

/** F20 follow-up scheduling — immediate suggestion if the target date is
 * within the 60-day horizon, otherwise deferred until it enters it. */
export function FollowUpForm({ bookingId }: { bookingId: string }) {
  const [weeks, setWeeks] = useState(4);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<FollowUpRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const followUp = await api.post<FollowUpRead>(`/api/v1/bookings/${bookingId}/follow-up`, { weeks });
      setResult(followUp);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not schedule a follow-up.");
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return (
      <p className="mt-2 text-xs text-teal-700">
        Follow-up scheduled around {new Date(result.target_date).toLocaleDateString()} ({result.status}).
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 flex flex-wrap items-center gap-2 text-xs">
      <label className="text-slate-500">Follow up in</label>
      <input
        type="number"
        min={1}
        max={52}
        value={weeks}
        onChange={(e) => setWeeks(Number(e.target.value))}
        className="w-16 rounded-md border border-slate-300 px-2 py-1"
      />
      <span className="text-slate-500">weeks</span>
      <button
        type="submit"
        disabled={submitting}
        className="rounded-md border border-teal-300 px-2 py-1 text-teal-700 hover:bg-teal-50 disabled:opacity-60"
      >
        {submitting ? "Scheduling…" : "Schedule"}
      </button>
      {error && <span className="text-red-600">{error}</span>}
    </form>
  );
}
