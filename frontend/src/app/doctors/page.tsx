"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { DoctorSearchResult, DoctorSortOrder, Page, SpecializationRead } from "@/lib/types";

export default function DoctorsPage() {
  const [specializations, setSpecializations] = useState<SpecializationRead[]>([]);
  const [specializationId, setSpecializationId] = useState("");
  const [city, setCity] = useState("");
  const [name, setName] = useState("");
  const [sort, setSort] = useState<DoctorSortOrder>("name");
  const [results, setResults] = useState<Page<DoctorSearchResult> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get<SpecializationRead[]>("/api/v1/doctors/specializations").then(setSpecializations);
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ page: String(page), page_size: "10", sort });
    if (specializationId) params.set("specialization_id", specializationId);
    if (city) params.set("city", city);
    if (name) params.set("name", name);
    const handle = setTimeout(() => {
      api
        .get<Page<DoctorSearchResult>>(`/api/v1/doctors?${params.toString()}`)
        .then(setResults)
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(handle);
  }, [specializationId, city, name, sort, page]);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Find a doctor</h1>

      <div className="mb-6 flex flex-wrap gap-3">
        <input
          placeholder="Search by doctor name"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <select
          value={specializationId}
          onChange={(e) => {
            setSpecializationId(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">All specializations</option>
          {specializations.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name_en}
            </option>
          ))}
        </select>
        <input
          placeholder="City"
          value={city}
          onChange={(e) => {
            setCity(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <select
          value={sort}
          onChange={(e) => {
            setSort(e.target.value as DoctorSortOrder);
            setPage(1);
          }}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="name">Sort: Name</option>
          <option value="fee_asc">Sort: Fee (low to high)</option>
          <option value="fee_desc">Sort: Fee (high to low)</option>
        </select>
      </div>

      {loading && <p className="text-slate-500">Loading…</p>}

      {!loading && results && results.items.length === 0 && (
        <p className="text-slate-500">No doctors match your search.</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {results?.items.map((doctor) => (
          <Link
            key={doctor.id}
            href={`/doctors/${doctor.id}`}
            className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md"
          >
            <p className="font-semibold text-slate-900">{doctor.full_name}</p>
            <p className="text-sm text-slate-600">{doctor.specialization.name_en}</p>
            <p className="mt-2 text-sm text-slate-500">
              {doctor.cities.join(", ") || "Location not set"}
            </p>
            <p className="mt-1 font-medium text-teal-700">Rs. {doctor.consultation_fee}</p>
            <p className="mt-1 text-xs text-slate-500">
              {doctor.next_available_slot_utc
                ? `Next available: ${new Date(doctor.next_available_slot_utc).toLocaleString()}`
                : "No slots in the next 2 weeks"}
            </p>
          </Link>
        ))}
      </div>

      {results && results.total > results.page_size && (
        <div className="mt-6 flex items-center justify-center gap-4">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-slate-600">
            Page {results.page} of {Math.ceil(results.total / results.page_size)}
          </span>
          <button
            disabled={page * results.page_size >= results.total}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
