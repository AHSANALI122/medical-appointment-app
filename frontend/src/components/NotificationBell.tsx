"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { NotificationRead, Page, UnreadCountRead } from "@/lib/types";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<NotificationRead[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const loadUnreadCount = useCallback(async () => {
    try {
      const res = await api.get<UnreadCountRead>("/api/v1/notifications/unread-count");
      setUnreadCount(res.unread_count);
    } catch {
      // Notification center is a convenience surface — a failed poll
      // shouldn't disrupt the rest of the page.
    }
  }, []);

  const loadNotifications = useCallback(async () => {
    try {
      const res = await api.get<Page<NotificationRead>>("/api/v1/notifications?page=1&page_size=20");
      setNotifications(res.items);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadUnreadCount();
    const interval = setInterval(loadUnreadCount, 30000);
    return () => clearInterval(interval);
  }, [loadUnreadCount]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function handleToggle() {
    const next = !open;
    setOpen(next);
    if (next) await loadNotifications();
  }

  async function handleMarkAllRead() {
    await api.post<UnreadCountRead>("/api/v1/notifications/read-all");
    setUnreadCount(0);
    setNotifications((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })));
  }

  async function handleMarkRead(id: string) {
    await api.post<NotificationRead>(`/api/v1/notifications/${id}/read`);
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)));
    setUnreadCount((prev) => Math.max(0, prev - 1));
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={handleToggle}
        className="relative rounded-md border border-slate-300 px-3 py-1.5 text-slate-700 hover:bg-slate-50"
        aria-label="Notifications"
      >
        🔔
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <span className="text-sm font-medium">Notifications</span>
            {unreadCount > 0 && (
              <button onClick={handleMarkAllRead} className="text-xs text-teal-700 underline">
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {notifications.length === 0 && (
              <p className="px-3 py-4 text-sm text-slate-500">No notifications yet.</p>
            )}
            {notifications.map((n) => (
              <button
                key={n.id}
                onClick={() => !n.read_at && handleMarkRead(n.id)}
                className={`block w-full border-b border-slate-50 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                  n.read_at ? "text-slate-500" : "bg-teal-50/50 font-medium text-slate-900"
                }`}
              >
                <div>{n.title}</div>
                <div className="text-xs font-normal text-slate-500">{n.body}</div>
                <div className="mt-0.5 text-[10px] text-slate-400">
                  {new Date(n.created_at).toLocaleString()}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
