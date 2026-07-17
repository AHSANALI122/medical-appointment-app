import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_ENVIRONMENT ?? "development",
  // Matches the backend's traces_sample_rate (app/main.py) so a single
  // request's frontend and backend spans are sampled at the same rate —
  // mismatched rates produce traces that dead-end halfway.
  tracesSampleRate: 0.1,
  enabled: Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN),
});
