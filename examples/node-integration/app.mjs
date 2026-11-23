import { createHmac, timingSafeEqual } from "node:crypto";
import express from "express";

const app = express();
const observations = new Map();

function secureEqual(first, second) {
  const left = Buffer.from(first ?? "");
  const right = Buffer.from(second);
  return left.length === right.length && timingSafeEqual(left, right);
}

function settings() {
  const origin = new URL(process.env.LOCALPAY_API_URL ?? "http://127.0.0.1:8000");
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]", "localhost", "api"].includes(origin.hostname)
    || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) {
    throw new Error("Set LOCALPAY_API_URL to the local simulator origin");
  }
  const id = process.env.LOCALPAY_KEY_ID;
  const secret = process.env.LOCALPAY_KEY_SECRET;
  if (!id?.startsWith("lp_test_") || !secret?.startsWith("lp_secret_")) throw new Error("Use LocalPay credentials");
  return { origin, auth: "Basic " + Buffer.from(id + ":" + secret).toString("base64") };
}

async function gateway(path, data) {
  const { origin, auth } = settings();
  const response = await fetch(new URL(path, origin), {
    method: "POST", headers: { authorization: auth, "content-type": "application/json" },
    body: JSON.stringify(data), redirect: "error", signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error("LocalPay returned HTTP " + response.status);
  return response.json();
}

app.get("/health", (request, response) => response.json({ status: "ok" }));

app.post("/webhook", express.raw({ type: "application/json", limit: "64kb" }), (request, response) => {
  const secret = process.env.LOCALPAY_RECEIVER_SECRET;
  const id = request.get("X-Razorpay-Event-Id");
  if (!secret || !id || id.length > 128 || !Buffer.isBuffer(request.body)) return response.sendStatus(400);
  const expected = createHmac("sha256", secret).update(request.body).digest("hex");
  if (!secureEqual(request.get("X-Razorpay-Signature"), expected)) return response.sendStatus(401);
  if (observations.has(id)) return response.json({ processed: false });
  let event;
  try {
    event = JSON.parse(request.body);
    if (typeof event?.event !== "string") return response.sendStatus(400);
  } catch {
    return response.sendStatus(400);
  }
  observations.set(id, { type: event.event, execution: request.get("X-LocalPay-Scenario-Execution") });
  return response.json({ processed: true });
});

app.get("/verify", (request, response) => {
  const token = process.env.LOCALPAY_VERIFICATION_TOKEN;
  if (!token || !secureEqual(request.get("Authorization"), "Bearer " + token)) return response.sendStatus(401);
  const execution = request.query.scenario_execution_id;
  if (typeof execution !== "string") return response.sendStatus(400);
  const count = Array.from(observations.values()).filter((item) => item.execution === execution).length;
  return response.json({ application_event_count: count });
});

app.post("/checkout", express.json({ limit: "64kb" }), async (request, response) => {
  const { amount = 600, outcome = "success", refund_amount } = request.body ?? {};
  if (!Number.isSafeInteger(amount) || amount < 100 || !["success", "failed"].includes(outcome)
    || (refund_amount !== undefined && (!Number.isSafeInteger(refund_amount) || refund_amount < 100))) {
    return response.sendStatus(422);
  }
  const order = await gateway("/v1/orders", { amount, currency: "INR" });
  let payment = await gateway("/localpay/v1/simulations/payments", { order_id: order.id, scenario: "payment." + outcome });
  let refund;
  if (outcome === "success") {
    payment = await gateway("/v1/payments/" + payment.id + "/capture", { amount, currency: "INR" });
    if (refund_amount !== undefined) refund = await gateway("/v1/payments/" + payment.id + "/refund", { amount: refund_amount });
  }
  return response.json({ order, payment, refund });
});

app.use((error, request, response, next) => {
  if (response.headersSent) return next(error);
  process.stderr.write("Example request failed: " + error.name + "\n");
  return response.status(error.status ?? 502).json({ error: "Example request failed" });
});

app.listen(Number(process.env.PORT ?? "9001"), process.env.LISTEN_HOST ?? "127.0.0.1");
