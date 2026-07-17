"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { MedicalHistoryRead } from "@/lib/types";
import { useFamilyProfiles } from "@/components/FamilyProfiles";

const FIELDS: { key: keyof FormState; label: string }[] = [
  { key: "blood_group", label: "Blood group" },
  { key: "allergies", label: "Allergies" },
  { key: "medications", label: "Current medications" },
  { key: "chronic_conditions", label: "Chronic conditions" },
  { key: "surgeries", label: "Past surgeries" },
];

interface FormState {
  blood_group: string;
  allergies: string;
  medications: string;
  chronic_conditions: string;
  surgeries: string;
}

const EMPTY_FORM: FormState = {
  blood_group: "",
  allergies: "",
  medications: "",
  chronic_conditions: "",
  surgeries: "",
};

function toForm(history: MedicalHistoryRead | null): FormState {
  if (!history) return EMPTY_FORM;
  return {
    blood_group: history.blood_group ?? "",
    allergies: history.allergies ?? "",
    medications: history.medications ?? "",
    chronic_conditions: history.chronic_conditions ?? "",
    surgeries: history.surgeries ?? "",
  };
}

/** F24 — per-PatientProfile medical history editor. Every save appends a
 * new version (server-side, append-only); this panel always shows the
 * latest and lets the patient page back through prior versions read-only. */
export function MedicalHistoryPanel() {
  const profiles = useFamilyProfiles();
  const [profileId, setProfileId] = useState<string>("");
  const [current, setCurrent] = useState<MedicalHistoryRead | null>(null);
  const [versions, setVersions] = useState<MedicalHistoryRead[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showHistory, setShowHistory] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!profileId && profiles.length > 0) {
      setProfileId(profiles.find((p) => p.relationship_label === "self")?.id ?? profiles[0].id);
    }
  }, [profiles, profileId]);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const history = await api.get<MedicalHistoryRead>(`/api/v1/patient-profiles/${id}/medical-history`);
      setCurrent(history);
      setForm(toForm(history));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setCurrent(null);
        setForm(EMPTY_FORM);
      } else {
        setError(err instanceof ApiError ? err.message : "Could not load medical history.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (profileId) load(profileId);
  }, [profileId, load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!profileId) return;
    setSaving(true);
    setError(null);
    try {
      const history = await api.put<MedicalHistoryRead>(`/api/v1/patient-profiles/${profileId}/medical-history`, {
        blood_group: form.blood_group || null,
        allergies: form.allergies || null,
        medications: form.medications || null,
        chronic_conditions: form.chronic_conditions || null,
        surgeries: form.surgeries || null,
      });
      setCurrent(history);
      setVersions([]);
      setShowHistory(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save medical history.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleHistory() {
    if (!showHistory && versions.length === 0 && profileId) {
      const list = await api.get<MedicalHistoryRead[]>(
        `/api/v1/patient-profiles/${profileId}/medical-history/versions`
      );
      setVersions(list);
    }
    setShowHistory((v) => !v);
  }

  if (profiles.length === 0) return null;

  return (
    <section>
      <h2 className="mb-1 text-xl font-semibold">Medical history</h2>
      <p className="mb-3 text-sm text-slate-500">
        Shared read-only with a doctor while you have an active booking with them. Encrypted at rest.
      </p>

      {profiles.length > 1 && (
        <select
          value={profileId}
          onChange={(e) => setProfileId(e.target.value)}
          className="mb-3 rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.relationship_label === "self" ? "Myself" : `${p.full_name} (${p.relationship_label})`}
            </option>
          ))}
        </select>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (
        <form onSubmit={handleSave} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2">
          {FIELDS.map(({ key, label }) => (
            <label key={key} className="flex flex-col gap-1 text-sm">
              <span className="text-slate-600">{label}</span>
              <input
                value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          ))}
          <div className="sm:col-span-2 flex items-center gap-3">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            {current && (
              <span className="text-xs text-slate-400">version {current.version}</span>
            )}
            <button type="button" onClick={toggleHistory} className="text-xs text-teal-700 hover:underline">
              {showHistory ? "Hide version history" : "View version history"}
            </button>
          </div>
        </form>
      )}

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      {showHistory && (
        <ul className="mt-3 flex flex-col gap-2 text-xs text-slate-500">
          {versions.map((v) => (
            <li key={v.id} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="font-medium text-slate-700">v{v.version}</span> —{" "}
              {new Date(v.created_at).toLocaleString()}
              {v.blood_group && <> · blood group: {v.blood_group}</>}
              {v.allergies && <> · allergies: {v.allergies}</>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
