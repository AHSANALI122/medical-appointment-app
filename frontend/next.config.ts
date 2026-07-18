import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (server.js + only the node_modules
  // files actually traced as used) so the production Docker image can ship
  // without the full dependency tree. See frontend/Dockerfile.
  output: "standalone",
};

// Source maps upload only when SENTRY_AUTH_TOKEN is present, so forks, local
// builds, and CI-without-secrets build normally instead of failing on a
// missing credential (F26 — see docs/observability.md).
const sentryEnabled = Boolean(process.env.SENTRY_AUTH_TOKEN);

// Only wrap with Sentry for production builds. `next dev` sets NODE_ENV to
// "development"; `next build` sets it to "production". Sentry is inert in dev
// anyway (no NEXT_PUBLIC_SENTRY_DSN, so Sentry.init runs disabled), but the
// build plugin still forces the heavy instrumentation (Node + Edge) compile,
// injects the client SDK, and adds the `/monitoring` tunnel route on every
// cold route — pure dev-server tax for zero benefit. Skipping it keeps prod
// behaviour byte-for-byte identical while cutting cold-compile time locally.
const isProduction = process.env.NODE_ENV === "production";

export default isProduction
  ? withSentryConfig(nextConfig, {
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
    })
  : nextConfig;
