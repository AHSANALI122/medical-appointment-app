"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { PatientProfileRead } from "@/lib/types";

/** F20 family accounts: add/list dependent profiles ('Ammi ke liye
 * booking'). Booking on behalf of one happens via BookingStepper's profile
 * selector, which reads the same list from this endpoint. */
export function FamilyProfiles() {
  const [profiles, setProfiles] = useState<PatientProfileRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [fullName, setFullName] = useState("");
  const [relationship, setRelationship] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<PatientProfileRead[]>("/api/v1/patient-profiles");
      setProfiles(res);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 403)) {
        setError(err instanceof ApiError ? err.message : "Could not load family profiles.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.post<PatientProfileRead>("/api/v1/patient-profiles", {
        full_name: fullName,
        relationship_label: relationship,
      });
      setFullName("");
      setRelationship("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add this profile.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return null;

  return (
    <section>
      <h2 className="mb-4 text-xl font-semibold">Family members</h2>
      <p className="mb-3 text-sm text-slate-500">
        Add a family member to book appointments on their behalf, like &quot;Ammi ke liye booking&quot;.
      </p>
      <ul className="mb-4 flex flex-col gap-2 text-sm text-slate-700">
        {profiles.map((p) => (
          <li key={p.id} className="rounded-md border border-slate-200 bg-white px-3 py-2">
            {p.full_name} <span className="text-slate-400">({p.relationship_label})</span>
          </li>
        ))}
      </ul>
      <form onSubmit={handleAdd} className="grid gap-2 sm:grid-cols-3">
        <input
          placeholder="Full name"
          required
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <input
          placeholder="Relationship (e.g. mother, son)"
          required
          value={relationship}
          onChange={(e) => setRelationship(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {submitting ? "Adding…" : "Add family member"}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </section>
  );
}

/** Compact selector used by BookingStepper — "book for" defaulting to self. */
export function useFamilyProfiles() {
  const [profiles, setProfiles] = useState<PatientProfileRead[]>([]);

  useEffect(() => {
    api
      .get<PatientProfileRead[]>("/api/v1/patient-profiles")
      .then(setProfiles)
      .catch(() => setProfiles([]));
  }, []);

  return profiles;
}
