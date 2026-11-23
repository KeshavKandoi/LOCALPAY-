import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const apiOrigin = process.env.LOCALPAY_E2E_API_URL ?? "http://127.0.0.1:8000";
const token = process.env.LOCALPAY_E2E_TOKEN;

async function signIn(page: Page) {
  if (!token) throw new Error("LOCALPAY_E2E_TOKEN is required");
  await page.goto("/");
  await page.getByLabel("Administration token").fill(token);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Dashboard" })).toBeVisible();
}

async function seed(request: APIRequestContext) {
  if (!token) throw new Error("LOCALPAY_E2E_TOKEN is required");
  const admin = { authorization: "Bearer " + token };
  const name = "Dashboard QA " + randomUUID().slice(0, 8);
  const projects = apiOrigin + "/localpay/admin/v1/projects";
  const created = await request.post(projects, { headers: admin, data: { name, slug: name.toLowerCase().replaceAll(" ", "-") } });
  expect(created.status()).toBe(201);
  const project = await created.json();
  const issued = await request.post(projects + "/" + project.id + "/credentials", { headers: admin, data: { label: "Browser contract" } });
  expect(issued.status()).toBe(201);
  const credential = await issued.json();
  const auth = { authorization: "Basic " + Buffer.from(credential.key_id + ":" + credential.secret).toString("base64") };
  const order = await request.post(apiOrigin + "/v1/orders", { headers: auth, data: { amount: 900, currency: "INR", receipt: "browser-order" } });
  expect(order.status()).toBe(200);
  const orderData = await order.json();
  const payment = await request.post(apiOrigin + "/localpay/v1/simulations/payments", { headers: auth, data: { order_id: orderData.id } });
  expect(payment.status()).toBe(201);
  const paymentData = await payment.json();
  const capture = await request.post(apiOrigin + "/v1/payments/" + paymentData.id + "/capture", { headers: auth, data: { amount: 900, currency: "INR" } });
  expect(capture.status()).toBe(200);
  const refund = await request.post(apiOrigin + "/v1/payments/" + paymentData.id + "/refund", { headers: auth, data: { amount: 300 } });
  expect(refund.status()).toBe(200);
  return { name, project, order: orderData.id as string, payment: paymentData.id as string, refund: (await refund.json()).id as string };
}

test("authentication protects the dashboard and mobile views fit", async ({ page, request }) => {
  const unauthorized = await request.get("/api/backend/projects");
  expect(unauthorized.status()).toBe(401);
  const sample = await seed(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("Administration token").fill("invalid");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Invalid administration token" })).toBeVisible();
  await signIn(page);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await expect(page.getByRole("heading", { name: "Payment activity" })).toBeVisible();
  await expect(page.getByText("INR 9.00")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.LOCALPAY_CAPTURE_PREVIEW) await page.screenshot({ path: "test-results/mobile-dashboard.png", fullPage: true });
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator(".workspace")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to LocalPay" })).toBeVisible();
});

test("real records, filters, detail, and upstream error state", async ({ page, request }) => {
  const sample = await seed(request);
  await signIn(page);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "Orders" }).click();
  await page.getByRole("textbox", { name: "Search records" }).fill("browser-order");
  await page.getByRole("button", { name: sample.order }).click();
  await expect(page.getByText(sample.payment, { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "Filter by status" }).selectOption("created");
  await expect(page.getByText("No matching orders.")).toBeVisible();
  await page.getByRole("link", { name: "Payments" }).click();
  await expect(page.getByRole("button", { name: sample.payment })).toBeVisible();
  await page.getByRole("link", { name: "Refunds" }).click();
  await expect(page.getByRole("button", { name: sample.refund })).toBeVisible();
  await page.route("**/dashboard/records/refunds?*", (route) => route.fulfill({ status: 502, body: "" }));
  await page.getByRole("textbox", { name: "Search records" }).fill("unavailable");
  await expect(page.getByRole("alert").filter({ hasText: "Could not reach the LocalPay API." })).toBeVisible();
});

test("webhook replay, payment chaos, reliability execution, and export", async ({ page, request }) => {
  const sample = await seed(request);
  await signIn(page);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByLabel("Receiver URL").fill("http://receiver.example.test/payments");
  await page.getByLabel("Webhook secret").fill(randomUUID());
  await page.getByLabel("Event subscriptions").selectOption("payment.captured");
  await page.getByRole("button", { name: "Register receiver" }).click();
  await expect(page.getByText("Receiver registered.")).toBeVisible();
  await page.getByRole("link", { name: "Webhooks" }).click();
  await page.getByRole("button", { name: "payment.captured", exact: true }).click();
  await page.getByLabel("Replay receiver").selectOption({ label: "http://receiver.example.test/payments" });
  await page.getByRole("button", { name: "Replay webhook" }).click();
  await expect(page.getByText("Replay queued.")).toBeVisible();
  await page.getByRole("link", { name: "Chaos Lab" }).click();
  await page.getByLabel("Payment scenario").selectOption("payment.concurrent_capture");
  await page.getByRole("button", { name: "Run payment scenario" }).click();
  await expect(page.getByText("succeeded", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Test Runner" }).click();
  await page.getByLabel("YAML definition").fill(
    "name: Browser smoke\ntests:\n  - name: Capture race\n    scenario: payment.concurrent_capture\n    assertions:\n      - type: amount_paid\n        expected: 600",
  );
  await page.getByRole("button", { name: "Save test suite" }).click();
  await expect(page.getByText("Test suite saved.")).toBeVisible();
  await page.getByRole("button", { name: "Run test suite" }).click();
  await expect(page.getByText("Run queued.")).toBeVisible();
  await expect(page.getByText("passed", { exact: true }).first()).toBeVisible({ timeout: 18000 });
  await page.getByRole("link", { name: "Reports" }).click();
  await page.getByRole("button", { name: "Browser smoke" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export HTML" }).click();
  expect((await download).suggestedFilename()).toMatch(/^localpay-report-.*\.html$/);
});

test("dashboard authentication caps request size and rejects cross-origin login", async ({ request, baseURL }) => {
  if (!token || !baseURL) throw new Error("Dashboard test environment is required");
  const origin = new URL(baseURL).origin;
  const csrf = await request.post("/api/session", { headers: { origin: "http://127.0.0.1:1" }, data: { token } });
  expect(csrf.status()).toBe(403);
  const oversized = await request.post("/api/session", { headers: { origin }, data: { token: "x".repeat(1100) } });
  expect(oversized.status()).toBe(413);
  let throttled = false;
  for (let attempt = 0; attempt < 21; attempt++) {
    const denied = await request.post("/api/session", { headers: { origin }, data: { token: "invalid" } });
    if (denied.status() === 429) {
      expect(Number(denied.headers()["retry-after"])).toBeGreaterThan(0);
      throttled = true;
      break;
    }
    expect(denied.status()).toBe(401);
  }
  expect(throttled).toBe(true);
  const valid = await request.post("/api/session", { headers: { origin }, data: { token } });
  expect(valid.status()).toBe(200);
  expect(valid.headers()["set-cookie"]).toContain("HttpOnly");
  expect(valid.headers()["set-cookie"]).not.toContain(token);
});
