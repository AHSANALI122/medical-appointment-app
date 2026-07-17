import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_ENVIRONMENT ?? "development",
  tracesSampleRate: 0.1,
  enabled: Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN),

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

// Required by Next.js App Router for navigation instrumentation.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
