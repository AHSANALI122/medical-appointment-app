import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
};

// Source maps upload only when SENTRY_AUTH_TOKEN is present, so forks, local
// builds, and CI-without-secrets build normally instead of failing on a
// missing credential (F26 — see docs/observability.md).
const sentryEnabled = Boolean(process.env.SENTRY_AUTH_TOKEN);

export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,

  silent: !process.env.CI,
  sourcemaps: {
    disable: !sentryEnabled,
    // Uploaded maps are deleted from the build output afterwards — leaving
    // them publicly served would hand anyone our unminified source.
    deleteSourcemapsAfterUpload: true,
  },
  // Routes Sentry's browser requests through our own origin so ad blockers
  // don't silently swallow error reports.
  tunnelRoute: "/monitoring",
});
