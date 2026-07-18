// Loaded in the browser. Sentry is imported lazily for the same reason as the
// server instrumentation: a static top-level `import * as Sentry` pulls the
// whole client SDK into every cold dev compile even though it is disabled
// without a DSN. Production (which sets NEXT_PUBLIC_SENTRY_DSN) is unchanged —
// init still runs, with the same PII-tightened config below.
const sentryEnabled = Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);

if (sentryEnabled) {
  void import("@sentry/nextjs").then((Sentry) => {
    Sentry.init({
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      environment: process.env.NEXT_PUBLIC_ENVIRONMENT ?? "development",
      tracesSampleRate: 0.1,
      enabled: true,

      // This app handles health data (CLAUDE.md rule 7: clinical notes, patient
      // notes, medical history and agent chat are encrypted at rest). An error
      // tracker that ships symptom text to a third party would route around
      // that entire policy, so the defaults are tightened deliberately:
      //
      //  - sendDefaultPii stays false: no cookies, no IP addresses, no request
      //    bodies. Sentry's own docs describe this as opt-in convenience; here
      //    it would be a disclosure.
      //  - Session Replay is NOT enabled. It records the DOM — on this app that
      //    means the chat panel and the medical-history form.
      sendDefaultPii: false,

      beforeBreadcrumb(breadcrumb) {
        // Console breadcrumbs capture whatever was logged, and the error
        // boundaries console.error the raw error. Drop them rather than audit
        // every call site forever.
        if (breadcrumb.category === "console") return null;
        return breadcrumb;
      },
    });
  });
}

// Required by Next.js App Router for navigation instrumentation. Wrapped so the
// SDK is only imported when Sentry is actually enabled.
export async function onRouterTransitionStart(
  ...args: Parameters<typeof import("@sentry/nextjs").captureRouterTransitionStart>
) {
  if (!sentryEnabled) return;
  const Sentry = await import("@sentry/nextjs");
  return Sentry.captureRouterTransitionStart(...args);
}
