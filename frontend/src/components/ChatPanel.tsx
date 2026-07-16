"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import type { BookingRead, ChatMessageRead, ChatMessageResponse, ChatSessionRead, Page } from "@/lib/types";
import { Countdown } from "@/components/Countdown";
import { StatusBadge } from "@/components/StatusBadge";

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  emergency?: boolean;
  draftBooking?: BookingRead | null;
}

export function ChatPanel() {
  const { user, loading: authLoading } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const init = useCallback(async () => {
    try {
      const session = await api.post<ChatSessionRead>("/api/v1/chat/sessions");
      setSessionId(session.id);
      const history = await api.get<Page<ChatMessageRead>>(
        `/api/v1/chat/sessions/${session.id}/messages?page=1&page_size=100`,
      );
      setMessages(
        history.items
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content })),
      );
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not start the assistant.");
    }
  }, []);

  useEffect(() => {
    if (!user || user.role !== "patient") return;
    init();
  }, [user, init]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || !sessionId || sending) return;

    setInput("");
    setMessages((prev) => [...prev, { id: `local-${Date.now()}`, role: "user", content: text }]);
    setSending(true);
    setLoadError(null);
    try {
      const res = await api.post<ChatMessageResponse>(`/api/v1/chat/sessions/${sessionId}/messages`, {
        message: text,
      });
      setMessages((prev) => [
        ...prev,
        {
          id: `local-${Date.now()}-r`,
          role: "assistant",
          content: res.reply,
          emergency: res.emergency,
          draftBooking: res.draft_booking,
        },
      ]);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "The assistant is unavailable right now.");
    } finally {
      setSending(false);
    }
  }

  if (authLoading) return <p className="text-slate-500">Loading…</p>;
  if (!user) return <p className="text-slate-500">Please log in as a patient to use the assistant.</p>;
  if (user.role !== "patient") {
    return <p className="text-slate-500">The assistant is available to patient accounts only.</p>;
  }

  return (
    <div className="flex h-[70vh] flex-col rounded-lg border border-slate-200 bg-white">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && !loadError && (
          <p className="text-sm text-slate-500">
            Ask me to find a doctor, book an appointment, or answer a question about MedBook — in
            English, Urdu, or Roman Urdu.
          </p>
        )}
        <div className="flex flex-col gap-3">
          {messages.map((m) => (
            <ChatBubble key={m.id} message={m} />
          ))}
        </div>
        <div ref={bottomRef} />
      </div>

      {loadError && <p className="border-t border-slate-100 px-4 py-2 text-sm text-red-600">{loadError}</p>}

      <form onSubmit={handleSend} className="flex items-center gap-2 border-t border-slate-200 p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          disabled={!sessionId || sending}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!sessionId || sending || !input.trim()}
          className="rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {sending ? "Sending…" : "Send"}
        </button>
      </form>
    </div>
  );
}

function ChatBubble({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[80%]">
        <div
          className={`rounded-lg px-3 py-2 text-sm ${
            message.emergency
              ? "border border-red-300 bg-red-50 text-red-900"
              : isUser
                ? "bg-teal-600 text-white"
                : "bg-slate-100 text-slate-800"
          }`}
        >
          {message.content}
        </div>
        {message.draftBooking && <DraftBookingCard booking={message.draftBooking} />}
      </div>
    </div>
  );
}

/** F18 HITL: the assistant only ever creates a `draft` hold — this card is
 * the explicit confirm tap, exactly like the manual BookingStepper's draft
 * step. No optimistic UI: the button waits for the server's ACK. */
function DraftBookingCard({ booking }: { booking: BookingRead }) {
  const [current, setCurrent] = useState(booking);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);

  async function handleConfirm() {
    setConfirming(true);
    setError(null);
    try {
      const confirmed = await api.post<BookingRead>(`/api/v1/bookings/${current.id}/confirm`);
      setCurrent(confirmed);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not confirm this booking.");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
      <div className="mb-1 flex items-center gap-2">
        <StatusBadge status={current.status} />
        {current.status === "draft" && current.expires_at && !expired && (
          <span className="text-xs text-amber-900">
            hold expires in <Countdown expiresAt={current.expires_at} onExpire={() => setExpired(true)} />
          </span>
        )}
      </div>
      <p className="text-slate-700">{new Date(current.start_time_utc).toLocaleString()}</p>
      <p className="text-slate-600">{current.address_snapshot}</p>
      <p className="text-slate-600">Fee: Rs. {current.fee_charged}</p>
      {error && <p className="mt-1 text-red-600">{error}</p>}
      {current.status === "draft" && !expired && (
        <button
          onClick={handleConfirm}
          disabled={confirming}
          className="mt-2 rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
        >
          {confirming ? "Confirming…" : "Confirm appointment"}
        </button>
      )}
      {expired && <p className="mt-1 text-xs text-slate-500">This hold expired — ask me to find another slot.</p>}
    </div>
  );
}
