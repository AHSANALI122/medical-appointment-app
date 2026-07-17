"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { UserPublic } from "@/lib/types";

/** F25 — lets a user opt into SMS-first delivery ahead of any email bounce.
 * Default path is in-app -> email -> SMS (only on bounce/failure); this is
 * the one setting that changes that priority. */
export function NotificationPreferenceToggle() {
  const { user, refresh } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!user) return null;
  const smsFirst = user.notification_preference === "sms_first";

  async function handleToggle() {
    setSaving(true);
    setError(null);
    try {
      await api.put<UserPublic>("/api/v1/auth/me/notification-preference", {
        notification_preference: smsFirst ? "default" : "sms_first",
      });
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update notification preference.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-1 rounded-lg border border-slate-200 bg-white p-4 text-sm">
      <label className="flex items-center gap-2 text-slate-700">
        <input type="checkbox" checked={smsFirst} disabled={saving} onChange={handleToggle} />
        Prefer SMS over email for booking notifications
      </label>
      <p className="text-xs text-slate-400">
        By default we email you and only fall back to SMS if the email fails to deliver. Turn this on to
        get SMS right away instead.
      </p>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
