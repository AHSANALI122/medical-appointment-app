"use client";

import { useEffect, useState } from "react";

export function Countdown({ expiresAt, onExpire }: { expiresAt: string; onExpire?: () => void }) {
  const [remainingMs, setRemainingMs] = useState(() => Date.parse(expiresAt) - Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      const remaining = Date.parse(expiresAt) - Date.now();
      setRemainingMs(remaining);
      if (remaining <= 0) {
        clearInterval(interval);
        onExpire?.();
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [expiresAt, onExpire]);

  const totalSeconds = Math.max(0, Math.floor(remainingMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const isUrgent = totalSeconds <= 120;

  return (
    <span className={`font-mono text-sm font-semibold ${isUrgent ? "text-red-600" : "text-slate-700"}`}>
      {minutes}:{seconds.toString().padStart(2, "0")}
    </span>
  );
}
