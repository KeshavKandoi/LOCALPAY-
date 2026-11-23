import { NextRequest, NextResponse } from "next/server";
import { BodyTooLarge, boundedBody } from "@/lib/request";
import { sameOrigin, sessionName, validSession } from "@/lib/session";

const payment = "pay_[a-zA-Z0-9]+";
const refund = "rfnd_[a-zA-Z0-9]+";
const routes = {
  read: new RegExp("^/(?:health|ready|localpay/v1/project|v1/orders(?:/order_[a-zA-Z0-9]+)?|v1/payments/" + payment + "(?:/refunds(?:/" + refund + ")?)?|v1/refunds/" + refund + ")$"),
  write: new RegExp("^/(?:v1/orders|v1/payments/" + payment + "/(?:capture|refund)|localpay/v1/simulations/(?:payments(?:/" + payment + "/refunds)?|refunds/" + refund + "/resolve))$"),
};
const projectPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const limit = 524288;

function fail(error: string, status: number) {
  return NextResponse.json({ error }, { status });
}

async function handle(request: NextRequest, context: { params: Promise<{ segments: string[] }> }) {
  if (!validSession(request.cookies.get(sessionName)?.value)) return fail("Sign in required.", 401);
  if (request.headers.has("origin") ? !sameOrigin(request) : request.headers.get("sec-fetch-site") !== "same-origin") {
    return fail("Invalid origin.", 403);
  }

  const { segments } = await context.params;
  const path = "/" + segments.join("/");
  const read = request.method === "GET" || request.method === "HEAD" || request.method === "OPTIONS";
  if (!(read ? routes.read : routes.write).test(path)) return fail("LocalPay endpoint unavailable.", 404);
  const health = path === "/health" || path === "/ready";
  const project = request.headers.get("x-localpay-workspace-project") ?? "";
  const authorization = request.headers.get("authorization") ?? "";
  if (!health && (!projectPattern.test(project) || !/^Basic [A-Za-z0-9+/]{1,512}={0,2}$/i.test(authorization))) {
    return fail("Enter a LocalPay key ID and secret for the selected project.", 401);
  }

  const root = process.env.LOCALPAY_API_URL ?? "http://127.0.0.1:8000";
  const signal = AbortSignal.any([request.signal, AbortSignal.timeout(10000)]);
  try {
    const body = read ? undefined : await boundedBody(request, limit, true);
    const headers = new Headers();
    for (const name of ["accept", "content-type", "x-localpay-idempotency-key", "x-refund-idempotency"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (!health) {
      headers.set("authorization", authorization);
      const identity = await fetch(new URL("/localpay/v1/project", root), {
        headers: { authorization }, redirect: "error", cache: "no-store", signal,
      });
      if (!identity.ok) {
        await identity.body?.cancel();
        if (identity.status === 401 || identity.status === 403) return fail("LocalPay credentials were rejected.", 401);
        return fail("Could not verify the LocalPay project.", 502);
      }
      if ((await identity.json()).id !== project) return fail("These credentials belong to a different project.", 403);
    }
    const target = new URL(path, root);
    target.search = request.nextUrl.search;
    const response = await fetch(target, { method: request.method, body, headers, signal, redirect: "error", cache: "no-store" });
    const bytes = await boundedBody(response, limit, true);
    const responseHeaders = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox" });
    for (const name of ["allow", "retry-after", "x-request-id"]) {
      const value = response.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    const contentType = response.headers.get("content-type");
    if (contentType) responseHeaders.set("x-localpay-content-type", contentType);
    responseHeaders.set("content-type", "application/octet-stream");
    return new Response(request.method === "HEAD" || [204, 205, 304].includes(response.status) ? null : bytes, {
      status: response.status, headers: responseHeaders,
    });
  } catch (error) {
    if (error instanceof BodyTooLarge) return fail("Request or response exceeded 512 KiB.", 413);
    if (signal.aborted) return fail("LocalPay request timed out or was cancelled.", 504);
    return fail("LocalPay API is unreachable.", 502);
  }
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE, handle as HEAD, handle as OPTIONS };
