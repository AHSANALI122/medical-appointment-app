// Sentry is loaded lazily so `next dev` never has to compile the SDK. In
// development there is no NEXT_PUBLIC_SENTRY_DSN, so Sentry would init disabled
// anyway (F26) — but a *static* `import * as Sentry` at the top of a Next
// file-convention forces Turbopack to bundle the whole SDK on every cold
// start ("Compiling instrumentation…"), which is dead weight on the slow local
// filesystem. Deferring the import behind the DSN check keeps production
// behaviour byte-for-byte identical while removing that cost in dev.
const sentryEnabled =
  process.env.NODE_ENV === "production" || Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);

export async function register() {
  if (!sentryEnabled) return;
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

export async function onRequestError(
  ...args: Parameters<typeof import("@sentry/nextjs").captureRequestError>
) {
  if (!sentryEnabled) return;
  const Sentry = await import("@sentry/nextjs");
  return Sentry.captureRequestError(...args);
}
