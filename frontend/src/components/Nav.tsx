"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { NotificationBell } from "@/components/NotificationBell";

const DASHBOARD_PATH: Record<string, string> = {
  doctor: "/dashboard/doctor",
  admin: "/dashboard/admin",
};

export function Nav() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/");
    router.refresh();
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="text-lg font-semibold text-teal-700">
          MedBook
        </Link>
        <div className="flex items-center gap-4 text-sm">
          <Link href="/doctors" className="text-slate-600 hover:text-slate-900">
            Find a doctor
          </Link>
          {loading ? null : user ? (
            <>
              <Link
                href={DASHBOARD_PATH[user.role] ?? "/dashboard/patient"}
                className="text-slate-600 hover:text-slate-900"
              >
                Dashboard
              </Link>
              {user.role === "patient" && (
                <Link href="/assistant" className="text-slate-600 hover:text-slate-900">
                  Assistant
                </Link>
              )}
              <NotificationBell />
              <span className="text-slate-400">{user.full_name}</span>
              <button
                onClick={handleLogout}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-slate-700 hover:bg-slate-50"
              >
                Log out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="text-slate-600 hover:text-slate-900">
                Log in
              </Link>
              <Link
                href="/register/patient"
                className="rounded-md bg-teal-600 px-3 py-1.5 text-white hover:bg-teal-700"
              >
                Sign up
              </Link>
            </>
          )}
        </div>
      </nav>
    </header>
  );
}
