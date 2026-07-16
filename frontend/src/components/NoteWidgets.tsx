"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ClinicalNoteRead, PatientNoteRead } from "@/lib/types";

/** Patient's own reason/symptoms note (F6) — editable by the owning patient. */
export function PatientNoteEditor({ bookingId }: { bookingId: string }) {
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PatientNoteRead>(`/api/v1/bookings/${bookingId}/patient-note`)
      .then((note) => {
        setContent(note.content);
        setSaved(true);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [bookingId]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.put<PatientNoteRead>(`/api/v1/bookings/${bookingId}/patient-note`, { content });
      setSaved(true);
      setEditing(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save note.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return null;

  if (saved && !editing) {
    return (
      <p className="mt-2 text-sm text-slate-600">
        <span className="font-medium text-slate-700">Reason for visit: </span>
        {content}{" "}
        <button onClick={() => setEditing(true)} className="text-teal-700 underline">
          edit
        </button>
      </p>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-1">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Reason for visit / symptoms (optional)"
        rows={2}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !content.trim()}
          className="rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && (
          <button onClick={() => setEditing(false)} className="text-xs text-slate-500 underline">
            cancel
          </button>
        )}
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

/** Read-only view of the patient's reason/symptoms, for the treating doctor. */
export function PatientNoteViewer({ bookingId }: { bookingId: string }) {
  const [content, setContent] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PatientNoteRead>(`/api/v1/bookings/${bookingId}/patient-note`)
      .then((note) => setContent(note.content))
      .catch(() => {});
  }, [bookingId]);

  if (!content) return null;
  return (
    <p className="mt-2 text-sm text-slate-600">
      <span className="font-medium text-slate-700">Patient&apos;s reason: </span>
      {content}
    </p>
  );
}

/** Doctor's clinical note, private by default with a per-note share toggle (F6). */
export function ClinicalNoteEditor({ bookingId }: { bookingId: string }) {
  const [content, setContent] = useState("");
  const [shared, setShared] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ClinicalNoteRead>(`/api/v1/bookings/${bookingId}/clinical-note`)
      .then((note) => {
        setContent(note.content);
        setShared(note.is_shared_with_patient);
        setSaved(true);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [bookingId]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.put<ClinicalNoteRead>(`/api/v1/bookings/${bookingId}/clinical-note`, {
        content,
        is_shared_with_patient: shared,
      });
      setSaved(true);
      setEditing(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save clinical note.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return null;

  if (saved && !editing) {
    return (
      <div className="mt-2 rounded-md bg-slate-50 p-2 text-sm text-slate-600">
        <span className="font-medium text-slate-700">Clinical note </span>
        <span className="text-xs text-slate-400">
          ({shared ? "shared with patient" : "private"})
        </span>
        <p>{content}</p>
        <button onClick={() => setEditing(true)} className="text-xs text-teal-700 underline">
          edit
        </button>
      </div>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-1 rounded-md bg-slate-50 p-2">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Clinical note (private by default)"
        rows={3}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
      <label className="flex items-center gap-2 text-xs text-slate-600">
        <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
        Share this note with the patient
      </label>
      <div className="flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={saving || !content.trim()}
          className="rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && (
          <button onClick={() => setEditing(false)} className="text-xs text-slate-500 underline">
            cancel
          </button>
        )}
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

/** Patient's read-only view of the doctor's clinical note — only renders once shared. */
export function ClinicalNoteViewer({ bookingId }: { bookingId: string }) {
  const [content, setContent] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ClinicalNoteRead>(`/api/v1/bookings/${bookingId}/clinical-note`)
      .then((note) => setContent(note.content))
      .catch(() => {
        // 403 (not shared yet) or 404 (no note yet) — nothing to show.
      });
  }, [bookingId]);

  if (!content) return null;
  return (
    <p className="mt-2 rounded-md bg-slate-50 p-2 text-sm text-slate-600">
      <span className="font-medium text-slate-700">Doctor&apos;s note: </span>
      {content}
    </p>
  );
}
