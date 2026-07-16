import type { BookingStatus } from "@/lib/types";

const STYLES: Record<BookingStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  pending: "bg-amber-100 text-amber-800",
  confirmed: "bg-teal-100 text-teal-800",
  completed: "bg-blue-100 text-blue-800",
  cancelled: "bg-red-100 text-red-700",
  rejected: "bg-red-100 text-red-700",
  expired: "bg-slate-100 text-slate-500",
  no_show: "bg-orange-100 text-orange-800",
};

const LABELS: Record<BookingStatus, string> = {
  draft: "Draft",
  pending: "Awaiting doctor",
  confirmed: "Confirmed",
  completed: "Completed",
  cancelled: "Cancelled",
  rejected: "Rejected",
  expired: "Expired",
  no_show: "No-show",
};

export function StatusBadge({ status }: { status: BookingStatus }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STYLES[status]}`}>
      {LABELS[status]}
    </span>
  );
}
