/**
 * F28 load test — 200 concurrent users browsing + 50 booking simultaneously.
 * Acceptance: p95 < 800ms, zero booking corruptions.
 *
 *   k6 run                            loadtest/booking_load_test.js
 *   k6 run -e BASE_URL=https://staging-api.medbook.pk loadtest/booking_load_test.js
 *   k6 run --out json=loadtest/report.json loadtest/booking_load_test.js
 *
 * Prerequisites: `uv run python scripts/seed_demo.py` against the target
 * environment (this reads the demo accounts it creates). Never point this
 * at production — it creates real bookings.
 *
 * "Zero booking corruptions" is checked structurally, not just by counting
 * 2xx: the booking_conflict/slot_unavailable 409 is the *correct* answer
 * when two VUs race for one slot (that's the partial unique index doing its
 * job), so a 409 is a pass. What must never happen is a 5xx, or a draft
 * coming back with a status other than 'draft' — that would mean the state
 * machine let something through.
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DEMO_PASSWORD = __ENV.DEMO_PASSWORD || "demo1234";

const bookingCorruptions = new Counter("booking_corruptions");
const slotConflicts = new Counter("slot_conflicts_expected");
const draftsCreated = new Counter("drafts_created");
const bookingErrors = new Rate("booking_error_rate");

export const options = {
  scenarios: {
    browsing: {
      executor: "constant-vus",
      vus: 200,
      duration: "1m",
      exec: "browse",
      tags: { scenario: "browsing" },
    },
    booking: {
      executor: "constant-vus",
      vus: 50,
      duration: "1m",
      exec: "book",
      tags: { scenario: "booking" },
      startTime: "5s", // let browsing warm the cache first
    },
  },
  thresholds: {
    // The F28 acceptance criterion.
    "http_req_duration{scenario:browsing}": ["p(95)<800"],
    "http_req_duration{scenario:booking}": ["p(95)<800"],
    // Any corruption at all fails the run.
    booking_corruptions: ["count==0"],
    // 409s are excluded from this rate — see book() below.
    booking_error_rate: ["rate<0.01"],
  },
};

export function browse() {
  group("browse directory", () => {
    const list = http.get(`${BASE_URL}/api/v1/doctors?page=1&page_size=20`, {
      tags: { name: "search_doctors" },
    });
    check(list, {
      "search 200": (r) => r.status === 200,
      "search returns items": (r) => Array.isArray(r.json("items")),
    });

    const items = list.status === 200 ? list.json("items") : [];
    if (items && items.length > 0) {
      const doctor = items[Math.floor(Math.random() * items.length)];
      const profile = http.get(`${BASE_URL}/api/v1/doctors/${doctor.id}`, {
        tags: { name: "doctor_profile" },
      });
      check(profile, { "profile 200": (r) => r.status === 200 });
    }
    sleep(1);
  });
}

function login(email) {
  const jar = http.cookieJar();
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email, password: DEMO_PASSWORD }),
    { headers: { "Content-Type": "application/json" }, tags: { name: "login" } },
  );
  if (res.status !== 200) return null;
  // The API uses double-submit CSRF: echo the non-httponly csrf_token cookie
  // back as a header on mutating requests (mirrors frontend/src/lib/api.ts).
  const cookies = jar.cookiesForURL(BASE_URL);
  return cookies.csrf_token ? cookies.csrf_token[0] : null;
}

export function book() {
  // One account per VU. Sharing a handful of patients across 50 VUs would
  // just hammer the "max 3 active drafts per profile" guard and measure
  // nothing — seed_demo.py provisions load1..load50 for exactly this.
  const email = `load${__VU}@demo.medbook.pk`;
  const csrf = login(email);
  if (!csrf) {
    bookingErrors.add(true);
    return;
  }

  const list = http.get(`${BASE_URL}/api/v1/doctors?page=1&page_size=5`);
  const items = list.status === 200 ? list.json("items") : [];
  if (!items || items.length === 0) return;

  const doctor = items[__VU % items.length];
  const profile = http.get(`${BASE_URL}/api/v1/doctors/${doctor.id}`);
  if (profile.status !== 200) return;

  const clinics = profile.json("clinic_locations");
  if (!clinics || clinics.length === 0) return;
  const clinic = clinics[0];

  const slots = http.get(
    `${BASE_URL}/api/v1/doctors/${doctor.id}/slots?clinic_location_id=${clinic.id}`,
    { tags: { name: "slots" } },
  );
  if (slots.status !== 200) return;
  const available = slots.json();
  if (!available || available.length === 0) return;

  // Deliberately contend: many VUs aim at the same few slots so the partial
  // unique index is actually exercised under load, rather than each VU
  // picking a private slot and proving nothing.
  const slot = available[Math.floor(Math.random() * Math.min(3, available.length))];

  const res = http.post(
    `${BASE_URL}/api/v1/bookings`,
    JSON.stringify({
      doctor_id: doctor.id,
      clinic_location_id: clinic.id,
      start_time_utc: slot.start_time_utc,
      end_time_utc: slot.end_time_utc,
    }),
    {
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      tags: { name: "create_draft" },
    },
  );

  if (res.status === 201) {
    draftsCreated.add(1);
    const status = res.json("status");
    // A freshly created booking is always a draft — an agent or a race must
    // never be able to produce anything else here (CLAUDE.md rule 5).
    if (status !== "draft") {
      bookingCorruptions.add(1);
    }
    bookingErrors.add(false);
  } else if (res.status === 409 || res.status === 422) {
    // Expected under contention: the slot was taken, or a draft-limit /
    // lead-time guard fired. This is the system working.
    slotConflicts.add(1);
    bookingErrors.add(false);
  } else if (res.status >= 500) {
    bookingCorruptions.add(1);
    bookingErrors.add(true);
  } else {
    bookingErrors.add(true);
  }

  sleep(1);
}

export function handleSummary(data) {
  return {
    "loadtest/summary.json": JSON.stringify(data, null, 2),
    stdout: `
F28 load test summary
  browsing p95:      ${data.metrics["http_req_duration{scenario:browsing}"]?.values?.["p(95)"]?.toFixed(1)} ms (threshold <800)
  booking  p95:      ${data.metrics["http_req_duration{scenario:booking}"]?.values?.["p(95)"]?.toFixed(1)} ms (threshold <800)
  drafts created:    ${data.metrics.drafts_created?.values?.count ?? 0}
  expected 409s:     ${data.metrics.slot_conflicts_expected?.values?.count ?? 0}
  CORRUPTIONS:       ${data.metrics.booking_corruptions?.values?.count ?? 0} (must be 0)
`,
  };
}
