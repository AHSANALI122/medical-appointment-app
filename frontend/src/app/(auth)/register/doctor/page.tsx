"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { DoctorRegisterResponse, SpecializationRead } from "@/lib/types";

export default function RegisterDoctorPage() {
  const router = useRouter();
  const { refresh } = useAuth();

  const [specializations, setSpecializations] = useState<SpecializationRead[]>([]);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [pmcNumber, setPmcNumber] = useState("");
  const [specializationId, setSpecializationId] = useState("");
  const [consultationFee, setConsultationFee] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .get<SpecializationRead[]>("/api/v1/doctors/specializations")
      .then((specs) => {
        setSpecializations(specs);
        if (specs.length > 0) setSpecializationId(specs[0].id);
      })
      .catch(() => setError("Could not load specializations. Please refresh."));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.post<DoctorRegisterResponse>("/api/v1/auth/register/doctor", {
        full_name: fullName,
        email,
        phone: phone || null,
        password,
        pmc_number: pmcNumber,
        specialization_id: specializationId,
        consultation_fee: Number(consultationFee),
      });
      await refresh();
      if (res.verification_status === "unverified") {
        setSubmitted(true);
      } else {
        router.push("/dashboard/doctor");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-md rounded-md border border-amber-200 bg-amber-50 p-6 text-center">
        <h1 className="mb-2 text-xl font-semibold text-amber-900">Account created</h1>
        <p className="text-amber-800">
          Your account is pending PMC verification. You&apos;ll be able to receive bookings once an
          admin verifies your registration number.
        </p>
        <Link href="/dashboard/doctor" className="mt-4 inline-block text-teal-700 hover:underline">
          Go to my dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="mb-6 text-2xl font-semibold">Create a doctor account</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Full name</label>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Phone (optional)</label>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Password</label>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">PMC registration number</label>
          <input
            required
            value={pmcNumber}
            onChange={(e) => setPmcNumber(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Specialization</label>
          <select
            required
            value={specializationId}
            onChange={(e) => setSpecializationId(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          >
            {specializations.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name_en}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Consultation fee (PKR)</label>
          <input
            type="number"
            required
            min={1}
            value={consultationFee}
            onChange={(e) => setConsultationFee(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:border-teal-500 focus:outline-none"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-teal-600 px-4 py-2 font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-600">
        Already have an account?{" "}
        <Link href="/login" className="text-teal-700 hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
