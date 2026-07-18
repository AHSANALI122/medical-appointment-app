import type { UserRole } from "@/lib/types";

// Single source of truth for "where does this role's dashboard live". Used by
// the nav link and the post-login redirect so a role can never be routed to
// the wrong dashboard (an admin landing on /dashboard/patient was a bug caused
// by two call sites disagreeing).
const DASHBOARD_PATH: Record<UserRole, string> = {
  patient: "/dashboard/patient",
  doctor: "/dashboard/doctor",
  admin: "/dashboard/admin",
};

export function dashboardPathForRole(role: UserRole): string {
  return DASHBOARD_PATH[role] ?? "/dashboard/patient";
}
