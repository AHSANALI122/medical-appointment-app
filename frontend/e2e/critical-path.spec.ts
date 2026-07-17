import { expect, test } from "@playwright/test";

/**
 * F30 critical path, runs on every PR:
 *   signup → search → book (draft) → confirm (pending) → doctor accepts (confirmed)
 *
 * Reminder-fires / complete / review are covered in the nightly full suite
 * (booking-lifecycle.spec.ts) because they need clock control on the server.
 *
 * Requires: backend on :8000 with `scripts/seed_demo.py` already run.
 */

const DEMO_PASSWORD = "demo1234";
const DOCTOR_EMAIL = "doctor1@demo.medbook.pk";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Unique per run — signup can only ever happen once per email.
 *
 * Not a `.invalid` domain, tempting as that is for a throwaway address:
 * the API validates with Pydantic's EmailStr, which rejects RFC 2606
 * reserved TLDs outright ("special-use or reserved name"). A subdomain of
 * the real domain is both valid and obviously non-production.
 */
function uniqueEmail() {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 10000)}@e2e.medbook.pk`;
}

test.describe("critical path", () => {
  test("patient signs up, searches, books, and the doctor accepts", async ({ page, request }) => {
    const email = uniqueEmail();

    // Resolve the demo doctor's id up front and book with *that* doctor.
    // Clicking whichever result lands first instead would make the accept
    // step non-deterministic: search sorts by name, so the first row is
    // "Dr. Ahmed Zubair" (seeded as doctor16), not doctor1 — and the test
    // would then log in as the wrong doctor and find nothing pending.
    const doctorLogin = await request.post(`${API_URL}/api/v1/auth/login`, {
      data: { email: DOCTOR_EMAIL, password: DEMO_PASSWORD },
    });
    expect(doctorLogin.ok()).toBeTruthy();
    const doctorProfile = await request.get(`${API_URL}/api/v1/doctors/me`);
    expect(doctorProfile.ok()).toBeTruthy();
    const doctorId = (await doctorProfile.json()).id;

    await test.step("sign up", async () => {
      await page.goto("/register/patient");
      await page.getByLabel("Full name").fill("E2E Test Patient");
      await page.getByLabel("Email").fill(email);
      await page.getByLabel("Password").fill(DEMO_PASSWORD);
      await page.getByRole("button", { name: "Create account" }).click();

      // Registration lands the patient in their dashboard, logged in.
      await expect(page).toHaveURL(/\/dashboard\/patient/);
    });

    await test.step("search the directory", async () => {
      await page.goto("/doctors");
      await expect(page.getByRole("heading", { name: "Find a doctor" })).toBeVisible();
      // Seeded demo doctors must be listed.
      await expect(page.getByRole("link").first()).toBeVisible();
    });

    await test.step("open a doctor and hold a slot (draft)", async () => {
      await page.goto(`/doctors/${doctorId}`);

      await expect(page.getByRole("heading", { name: "1. Choose a slot" })).toBeVisible();

      // Slots are generated from the seeded availability rules; take the first.
      const firstSlot = page.locator("button").filter({ hasText: /^\d{1,2}:\d{2}/ }).first();
      await expect(firstSlot).toBeVisible();
      await firstSlot.click();

      await expect(page.getByRole("heading", { name: "2. Review" })).toBeVisible();
      await page.getByRole("button", { name: "Hold this slot" }).click();
    });

    await test.step("confirm the draft (draft → pending)", async () => {
      await expect(page.getByRole("heading", { name: "3. Confirm your appointment" })).toBeVisible();

      // F18: the draft card carries a live 10-minute countdown.
      await expect(page.getByText(/\d+:\d{2}/).first()).toBeVisible();

      await page.getByRole("button", { name: "Confirm appointment" }).click();

      // No optimistic UI on confirmation (CLAUDE.md): this only appears
      // after the server ACKs the transition.
      await expect(page.getByRole("heading", { name: "Request sent!" })).toBeVisible();
    });

    await test.step("booking shows as pending on the patient dashboard", async () => {
      await page.goto("/dashboard/patient");
      // The UI shows the patient-facing label, not the raw status — a
      // patient is told "Awaiting doctor", never "pending" (StatusBadge.tsx).
      // Asserting the enum here would test the API through the DOM.
      await expect(page.getByText("Awaiting doctor").first()).toBeVisible();
    });

    await test.step("doctor accepts (pending → confirmed)", async () => {
      // Driven through the API rather than the doctor UI: this test's subject
      // is the patient's path, and we need a deterministic accept, not a
      // second browser session racing the first. `request` is already
      // authenticated as the doctor from the lookup above.
      const pending = await request.get(`${API_URL}/api/v1/bookings/doctor/me?status=pending`);
      expect(pending.ok()).toBeTruthy();
      const body = await pending.json();
      expect(body.items.length).toBeGreaterThan(0);

      const csrf = (await request.storageState()).cookies.find((c) => c.name === "csrf_token");
      const accept = await request.post(
        `${API_URL}/api/v1/bookings/${body.items[0].id}/accept`,
        { headers: csrf ? { "X-CSRF-Token": csrf.value } : {} },
      );
      expect(accept.ok()).toBeTruthy();
      expect((await accept.json()).status).toBe("confirmed");
    });

    await test.step("patient sees it confirmed", async () => {
      await page.goto("/dashboard/patient");
      await expect(page.getByText("Confirmed").first()).toBeVisible();
      // And the pending state is genuinely gone, not just scrolled past.
      await expect(page.getByText("Awaiting doctor")).toHaveCount(0);
    });
  });

  test("health endpoint is reachable and reports ok", async ({ request }) => {
    // The external uptime monitor polls this (docs/observability.md), so a
    // regression in its status code is a monitoring outage.
    const response = await request.get(`${API_URL}/health`);
    expect(response.status()).toBe(200);
    expect((await response.json()).status).toBe("ok");
  });
});
