import { BodyTooLarge, boundedBody } from "@/lib/request";
import { NextRequest, NextResponse } from "next/server";
import { sameOrigin, sessionName, validSession } from "@/lib/session";

const uuid = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}";
const projectPaths = new RegExp(
  "^projects/" + uuid + "/(?:credentials(?:/" + uuid + "(?:/rotate)?)?|dashboard/(?:overview|records/(?:orders|payments|refunds)(?:/(?:order|pay|rfnd)_[a-zA-Z0-9]+)?|events/" + uuid + "/replay)|webhook-(?:endpoints(?:/" + uuid + ")?|events(?:/" + uuid + "/(?:payload|signed/" + uuid + "))?|deliveries(?:/" + uuid + "/attempts)?|scenarios(?:/" + uuid + "/runs)?|runs/" + uuid + "(?:/deliveries)?)|payment-chaos/(?:scenarios|runs(?:/" + uuid + "(?:/cancel)?)?)|test-suites(?:/validate|/" + uuid + "/runs)?|test-runs(?:/" + uuid + "(?:/(?:json|report/(?:json|html|junit)))?)?)$"
);

async function handle(request: NextRequest, context: { params: Promise<{ segments: string[] }> }) {
  if (!validSession(request.cookies.get(sessionName)?.value)) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401 });
  }
  if (request.method !== "GET" && !sameOrigin(request)) {
    return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  }
  const { segments } = await context.params;
  const path = segments.join("/");
  const root = process.env.LOCALPAY_API_URL ?? "http://127.0.0.1:8000";
  const destination = path === "health" || path === "ready"
    ? "/" + path
    : path === "projects" || projectPaths.test(path) ? "/localpay/admin/v1/" + path : null;
  if (!destination) return NextResponse.json({ error: "Resource unavailable" }, { status: 404 });
  try {
    const target = new URL(destination, root);
    target.search = request.nextUrl.search;
    const response = await fetch(target, {
      method: request.method, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
      body: request.method === "GET" ? undefined : await boundedBody(request, 196608),
      headers: { Authorization: "Bearer " + process.env.LOCALPAY_ADMIN_TOKEN, "Content-Type": "application/json" },
    });
    const headers = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const key of ["Content-Type", "Content-Disposition", "Content-Security-Policy", "X-Razorpay-Signature", "X-Razorpay-Event-Id"]) {
      const value = response.headers.get(key);
      if (value) headers.set(key, value);
    }
    return new Response(response.body, { status: response.status, headers });
  } catch (error) {
    if (error instanceof BodyTooLarge) return NextResponse.json({ error: "Request too large" }, { status: 413 });
    return NextResponse.json({ error: "LocalPay API is unreachable" }, { status: 502 });
  }
}

export { handle as GET, handle as POST, handle as DELETE, handle as PATCH };
