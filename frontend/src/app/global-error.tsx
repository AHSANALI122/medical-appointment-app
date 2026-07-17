"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 text-center text-slate-900">
        <h1 className="text-xl font-semibold">MedBook hit an unexpected error</h1>
        <p className="max-w-md text-sm text-slate-600">
          Please try again. If this keeps happening, the manual booking flow is still reachable once the
          page reloads.
        </p>
        <button
          onClick={reset}
          className="rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700"
        >
          Try again
        </button>
      </body>
    </html>
  );
}
