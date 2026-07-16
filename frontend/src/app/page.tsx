import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col items-center gap-8 py-16 text-center">
      <h1 className="max-w-2xl text-4xl font-bold tracking-tight text-slate-900">
        Book verified doctors near you, in minutes.
      </h1>
      <p className="max-w-xl text-lg text-slate-600">
        Search by specialization, see real fees and clinic locations upfront, and confirm your
        appointment with a doctor who accepts it — no surprises.
      </p>
      <div className="flex gap-4">
        <Link
          href="/doctors"
          className="rounded-md bg-teal-600 px-6 py-3 font-medium text-white hover:bg-teal-700"
        >
          Find a doctor
        </Link>
        <Link
          href="/register/doctor"
          className="rounded-md border border-slate-300 px-6 py-3 font-medium text-slate-700 hover:bg-slate-50"
        >
          I&apos;m a doctor
        </Link>
      </div>
    </div>
  );
}
