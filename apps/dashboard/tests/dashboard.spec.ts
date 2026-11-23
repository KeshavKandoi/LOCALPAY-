import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const apiOrigin = process.env.LOCALPAY_E2E_API_URL ?? "http://127.0.0.1:8000";
const token = process.env.LOCALPAY_E2E_TOKEN;

const accountPath = apiOrigin + "/localpay/account/v1";

async function register(request: APIRequestContext) {
  const username = "qa-" + randomUUID().slice(0, 12);
  const password = randomUUID();
  const response = await request.post(accountPath + "/signup", { data: { username, password, confirm_password: password } });
  expect(response.status()).toBe(201);
  return { username, password, headers: { authorization: "Bearer " + (await response.json()).token } };
}

async function signIn(page: Page, account: { username: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Username", { exact: true }).fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Dashboard" })).toBeVisible();
}

async function seed(request: APIRequestContext, account?: Awaited<ReturnType<typeof register>>) {
  account ??= await register(request);
  const name = "Dashboard QA " + randomUUID().slice(0, 8);
  const created = await request.post(accountPath + "/projects", { headers: account.headers, data: { name, slug: name.toLowerCase().replaceAll(" ", "-") } });
  expect(created.status()).toBe(201);
  const project = await created.json();
  const issued = await request.post(apiOrigin + "/account/localpay/admin/v1/projects/" + project.id + "/credentials", { headers: account.headers, data: { label: "Browser contract" } });
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
  return { name, account, project, credential, order: orderData.id as string, payment: paymentData.id as string, refund: (await refund.json()).id as string };
}

test("authentication protects the dashboard and mobile views fit", async ({ page, request }) => {
  const unauthorized = await request.get("/api/backend/projects");
  expect(unauthorized.status()).toBe(401);
  const sample = await seed(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill(sample.account.username);
  await page.getByLabel("Password", { exact: true }).fill("wrong password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Incorrect username or password" })).toBeVisible();
  await signIn(page, sample.account);
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
  await signIn(page, sample.account);
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
  await signIn(page, sample.account);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByLabel("Receiver URL").fill("http://receiver.example.test/payments");
  const webhookSecret = randomUUID();
  await page.getByLabel("Webhook secret").fill(webhookSecret);
  await page.getByLabel("Event subscriptions").selectOption("payment.captured");
  await page.getByRole("button", { name: "Register receiver" }).click();
  await expect(page.getByText("Receiver registered.")).toBeVisible();
  await page.getByRole("link", { name: "Webhooks" }).click();
  await page.getByRole("button", { name: "payment.captured", exact: true }).click();
  await page.getByLabel("Signature receiver").selectOption({ label: "http://receiver.example.test/payments" });
  await page.getByLabel("Verification secret").fill(webhookSecret);
  await page.getByRole("button", { name: "Verify webhook signature" }).click();
  await expect(page.getByText("Signature verified against the original payload bytes.")).toBeVisible();
  await page.getByLabel("Replay receiver").selectOption({ label: "http://receiver.example.test/payments" });
  await page.getByRole("button", { name: "Replay webhook" }).click();
  await expect(page.getByText("Replay queued.")).toBeVisible();
  await page.getByRole("link", { name: "Chaos Lab" }).click();
  await page.getByLabel("Payment scenario").selectOption("payment.concurrent_capture");
  await page.getByRole("button", { name: "Run payment scenario" }).click();
  await expect(page.getByText("succeeded", { exact: true }).first()).toBeVisible();

  await page.getByRole("link", { name: "Test Runner" }).click();
  await page.getByLabel("YAML definition").fill(
    "name: Browser smoke\ntests:\n  - name: Capture race\n    scenario: payment.concurrent_capture\n    assertions:\n      - type: amount_paid\n        expected: 600",
  );
  await page.getByRole("button", { name: "Validate draft" }).click();
  await expect(page.getByText("Suite definition is valid.")).toBeVisible();
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
  const junit = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export JUnit" }).click();
  expect((await junit).suggestedFilename()).toMatch(/^localpay-report-.*\.xml$/);
});

test("dashboard authentication caps request size and rejects cross-origin login", async ({ request, baseURL }) => {
  if (!baseURL) throw new Error("Dashboard test environment is required");
  const origin = new URL(baseURL).origin;
  const account = await register(request);
  const csrf = await request.post("/api/session", { headers: { origin: "http://127.0.0.1:1" }, data: account });
  expect(csrf.status()).toBe(403);
  const oversized = await request.post("/api/session", { headers: { origin }, data: { password: "x".repeat(4200) } });
  expect(oversized.status()).toBe(413);
  const valid = await request.post("/api/session", { headers: { origin }, data: { username: account.username, password: account.password } });
  expect(valid.status()).toBe(200);
  expect(valid.headers()["set-cookie"]).toContain("HttpOnly");
  expect(valid.headers()["set-cookie"]).toContain("SameSite=strict");
  expect(await valid.json()).toEqual({ authenticated: true, username: account.username });
  const forbidden = await request.delete("/api/session", { headers: { origin: "http://127.0.0.1:1" } });
  expect(forbidden.status()).toBe(403);
  const username = "absent-" + randomUUID().slice(0, 10);
  let throttled = false;
  for (let attempt = 0; attempt < 20; attempt++) {
    const denied = await request.post("/api/session", { headers: { origin }, data: { username, password: "invalid" } });
    if (denied.status() === 429) {
      expect(Number(denied.headers()["retry-after"])).toBeGreaterThan(0);
      throttled = true;
      break;
    }
    expect(denied.status()).toBe(401);
  }
  expect(throttled).toBe(true);
});

test("API Workspace sends real requests and isolates selected projects", async ({ page, request }) => {
  const unauthorized = await request.get("/api/workspace/health");
  expect(unauthorized.status()).toBe(401);
  const sample = await seed(request);
  const other = await seed(request, sample.account);
  await signIn(page, sample.account);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "API Workspace" }).click();
  await page.getByRole("button", { name: "Environment", exact: true }).click();
  await page.getByRole("textbox", { name: /^Variables / }).fill("receipt=workspace-real-order");
  await page.getByRole("button", { name: "Request", exact: true }).click();
  await page.getByLabel("Payment request templates").selectOption({ label: "Create order" });
  await page.getByLabel("Request body").fill('{"amount":50000,"currency":"INR","receipt":"{{receipt}}"}');
  await page.getByLabel("Key ID", { exact: true }).fill(sample.credential.key_id);
  await page.getByLabel("Key secret", { exact: true }).fill(sample.credential.secret);
  await page.getByLabel("Response assertions").fill("status = 200\njson.id exists\njson.amount = 50000");
  await page.getByRole("button", { name: "Save request" }).click();
  await page.getByRole("button", { name: "Send request" }).click();
  const viewer = page.getByRole("region", { name: "Response viewer" });
  await expect(viewer.getByRole("status")).toContainText("HTTP 200");
  await expect(viewer.getByText("Passed", { exact: true })).toHaveCount(3);
  await expect(viewer.locator("pre")).toContainText("workspace-real-order");
  const proxy = await page.evaluate(async ({ project, other }) => {
    const headers = {
      "x-localpay-workspace-project": project,
      authorization: "Basic " + btoa(other.key_id + ":" + other.secret),
    };
    const rejected = await fetch("/api/workspace/v1/orders", { headers });
    const unsupported = await fetch("/api/workspace/localpay/admin/v1/projects", { headers });
    return { rejected: rejected.status, unsupported: unsupported.status };
  }, { project: sample.project.id, other: other.credential });
  expect(proxy).toEqual({ rejected: 403, unsupported: 404 });
  await page.reload();
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByText("POST · HTTP 200", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Open saved request" }).click();
  await expect(page.getByLabel("Key secret", { exact: true })).toHaveValue("");
  await page.getByLabel("Key ID", { exact: true }).fill(sample.credential.key_id);
  await page.getByLabel("Key secret", { exact: true }).fill(sample.credential.secret);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(viewer.getByRole("status")).toContainText("HTTP 400");
  await expect(viewer.locator("pre")).toContainText("Duplicate request.");
  const stored = await page.evaluate(() => Object.values(localStorage).join("\n"));
  expect(stored).not.toContain(sample.credential.secret);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: other.name });
  await page.getByRole("button", { name: "Collections", exact: true }).click();
  await expect(page.getByText("No saved requests.")).toBeVisible();
});

test("Payment Simulator runs the order, authorization, capture, and refund lifecycle", async ({ page, request }) => {
  const sample = await seed(request);
  await signIn(page, sample.account);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "Payment Simulator" }).click();
  await page.getByLabel("Key ID", { exact: true }).fill(sample.credential.key_id);
  await page.getByLabel("Key secret", { exact: true }).fill(sample.credential.secret);
  await page.getByLabel("Amount in minor currency units").fill("900");
  await page.getByLabel("Receipt").fill("simulator-lifecycle");
  await page.getByRole("button", { name: "Create order", exact: true }).click();
  const lifecycle = page.getByRole("region", { name: "Payment lifecycle" });
  await expect(lifecycle.getByText("order · created")).toBeVisible();
  await page.getByRole("button", { name: "Simulate payment", exact: true }).click();
  await expect(lifecycle.getByText("payment · authorized")).toBeVisible();
  await page.getByRole("button", { name: "Capture payment", exact: true }).click();
  await expect(lifecycle.getByText("payment · captured")).toBeVisible();
  await page.getByLabel("Amount (blank for full refund)").fill("300");
  await page.getByRole("button", { name: "Refund payment", exact: true }).click();
  await expect(lifecycle.getByText("refund · processed")).toBeVisible();
  const result = page.getByRole("region", { name: "Payment action response" });
  await expect(result.getByRole("status")).toContainText("HTTP 200");
  await expect(result.locator("pre")).toContainText('"amount": 300');
});

test("API Workspace imports LocalPay paths from OpenAPI, Postman, and cURL", async ({ page, request }) => {
  const sample = await seed(request);
  await signIn(page, sample.account);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "API Workspace" }).click();
  await page.getByRole("button", { name: "Collections", exact: true }).click();
  const input = page.getByLabel("Import requests");
  await input.setInputFiles({ name: "orders.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({
    openapi: "3.1.0", info: { title: "Orders" }, paths: { "/v1/orders/{order_id}": { get: { summary: "Read order" } } },
  })) });
  await expect(page.getByRole("button", { name: "Orders / Read order" })).toBeVisible();
  await input.setInputFiles({ name: "collection.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({
    info: { name: "Gateway", schema: "https://schema.getpostman.com/json/collection/v2.1.0/collection.json" }, item: [{
      name: "Orders", item: [{ name: "List", request: { method: "GET", url: "{{baseUrl}}/v1/orders" } }],
    }],
  })) });
  await expect(page.getByRole("button", { name: "Gateway/Orders / List" })).toBeVisible();
  await input.setInputFiles({ name: "health.curl", mimeType: "text/plain", buffer: Buffer.from("curl -X GET 'https://example.com/health'") });
  await page.getByRole("button", { name: "cURL imports / GET /health" }).click();
  await expect(page.getByLabel("Request URL")).toHaveValue("/health");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("region", { name: "Response viewer" }).getByRole("status")).toContainText("HTTP 200");
});

test("suite validation is non-mutating and payment runs are project scoped", async ({ request }) => {
  const first = await seed(request);
  const second = await seed(request);
  const root = (id: string) => apiOrigin + "/localpay/admin/v1/projects/" + id;
  const headers = { authorization: "Bearer " + token };
  const suite = { yaml: "name: Draft validation\ntests:\n  - name: Capture\n    scenario: payment.concurrent_capture\n    assertions:\n      - type: amount_paid\n        expected: 600" };
  const unauthenticated = await request.post(root(first.project.id) + "/test-suites/validate", { data: suite });
  expect(unauthenticated.status()).toBe(401);
  const validation = await request.post(root(first.project.id) + "/test-suites/validate", { headers, data: suite });
  expect(validation.status()).toBe(200);
  expect((await validation.json()).name).toBe("Draft validation");
  const invalid = await request.post(root(first.project.id) + "/test-suites/validate", { headers, data: { yaml: "tests: false" } });
  expect(invalid.status()).toBe(422);
  const suites = await request.get(root(first.project.id) + "/test-suites", { headers });
  expect(await suites.json()).toEqual([]);
  const started = await request.post(root(first.project.id) + "/payment-chaos/runs", { headers, data: { type: "payment.gateway_outage" } });
  expect(started.status()).toBe(201);
  const run = await started.json();
  const own = await request.get(root(first.project.id) + "/payment-chaos/runs", { headers });
  expect(await own.json()).toEqual([expect.objectContaining({ id: run.id, scenario_type: "payment.gateway_outage" })]);
  const foreign = await request.get(root(second.project.id) + "/payment-chaos/runs", { headers });
  expect(await foreign.json()).toEqual([]);
  const canceled = await request.post(root(first.project.id) + "/payment-chaos/runs/" + run.id + "/cancel", { headers });
  expect(canceled.status()).toBe(204);
});

test("external workspace traffic goes directly from the browser without project credentials", async ({ page, request }) => {
  const sample = await seed(request);
  await signIn(page, sample.account);
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: sample.name });
  await page.getByRole("link", { name: "API Workspace" }).click();
  await page.getByLabel("Key ID", { exact: true }).fill(sample.credential.key_id);
  await page.getByLabel("Key secret", { exact: true }).fill(sample.credential.secret);
  await page.getByLabel("External HTTPS request").check();
  await page.getByLabel("Request URL").fill("https://127.0.0.1/health");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "require an HTTPS hostname" })).toBeVisible();
  const external = "https://workspace.mock.example.com/status";
  await page.route(external, async (route) => {
    const sent = await route.request().allHeaders();
    expect(sent.authorization).toBeUndefined();
    expect(sent.cookie).toBeUndefined();
    expect(sent["x-localpay-workspace-project"]).toBeUndefined();
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"external":true}', headers: { "Access-Control-Allow-Origin": "*" } });
  });
  await page.getByLabel("Request URL").fill(external);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("region", { name: "Response viewer" }).locator("pre")).toContainText('"external": true');
});

test("signup, password change and project isolation across accounts", async ({ page, request }) => {
  const username = "signup-" + randomUUID().slice(0, 8);
  const password = randomUUID();
  const newPassword = randomUUID();
  await page.goto("/signup");
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign up", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Create project" })).toBeVisible();
  await page.getByLabel("Project name", { exact: true }).fill("Owner workspace");
  await page.getByLabel("Project slug", { exact: true }).fill(username);
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await page.getByRole("combobox", { name: "Project" }).selectOption({ label: "Owner workspace" });
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByLabel("New project name", { exact: true }).fill("Renamed owner workspace");
  await page.getByRole("button", { name: "Save project name" }).click();
  await expect(page.getByText("Project name updated.")).toBeVisible();
  const duplicate = await request.post(accountPath + "/signup", { data: { username: username.toUpperCase(), password, confirm_password: password } });
  expect(duplicate.status()).toBe(409);
  const login = await request.post(accountPath + "/login", { data: { username, password } });
  expect(login.status()).toBe(200);
  const headers = { authorization: "Bearer " + (await login.json()).token };
  const foreign = await seed(request);
  const target = "projects/" + foreign.project.id;
  const privateRoutes = ["/dashboard/overview", "/dashboard/records/orders", "/dashboard/records/refunds", "/webhook-events", "/payment-chaos/runs", "/test-runs"];
  for (const suffix of privateRoutes) {
    const denied = await page.request.get("/api/backend/" + target + suffix);
    expect(denied.status()).toBe(404);
  }
  expect((await request.get(apiOrigin + "/localpay/admin/v1/projects", { headers })).status()).toBe(401);
  await page.getByRole("link", { name: "Account Settings" }).click();
  await page.getByLabel("Current password", { exact: true }).fill(password);
  await page.getByLabel("New password", { exact: true }).fill(newPassword);
  await page.getByLabel("Confirm new password", { exact: true }).fill(newPassword);
  await page.getByRole("button", { name: "Change password", exact: true }).click();
  await expect(page.getByText("Password updated. Other sessions were signed out.")).toBeVisible();
  expect((await request.get(accountPath + "/session", { headers })).status()).toBe(401);
  expect((await request.post(accountPath + "/login", { data: { username, password } })).status()).toBe(401);
  await page.getByRole("button", { name: "Sign out of this session" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to LocalPay" })).toBeVisible();
  await signIn(page, { username, password: newPassword });
});
