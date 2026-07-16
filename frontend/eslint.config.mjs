import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // This app's data-fetching pages intentionally call setState (loading
      // flags, fetched data) inside effects on mount/dep-change — the
      // standard "fetch in an effect" pattern. This rule flags all of them
      // as potential cascading-render risk, but at our data volumes that's
      // not a real perf concern, so it'd just be noise on every page.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
