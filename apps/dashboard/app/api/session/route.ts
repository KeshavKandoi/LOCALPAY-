import { BodyTooLarge, boundedBody } from "@/lib/request";
import { NextRequest, NextResponse } from "next/server";
import { newSession, sameOrigin, secureCookies, sessionName, sessionSeconds, tokenMatches, validSession } from "@/lib/session";

let failureWindow = 0;
let rejectedLogins = 0;

function failedLogin(): NextResponse {
  const now = Date.now();
  if (now >= failureWindow) {
    failureWindow = now + 30000;
    rejectedLogins = 0;
  }
  rejectedLogins += 1;
  if (rejectedLogins > 20) {
    const retry = Math.ceil((failureWindow - now) / 1000);
    return NextResponse.json({ error: "Too many unsuccessful attempts" }, { status: 429, headers: { "Retry-After": String(retry) } });
  }
  return NextResponse.json({ error: "Invalid administration token" }, { status: 401 });
}

export function GET(request: NextRequest) {
  return NextResponse.json({ authenticated: validSession(request.cookies.get(sessionName)?.value) }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  let body: { token?: unknown };
  try {
    body = JSON.parse(await boundedBody(request, 1024));
  } catch (error) {
    if (error instanceof BodyTooLarge) return NextResponse.json({ error: "Request too large" }, { status: 413 });
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
  if (!body || typeof body.token !== "string" || !tokenMatches(body.token)) {
    return failedLogin();
  }
  const response = NextResponse.json({ authenticated: true });
  response.cookies.set(sessionName, newSession(), { httpOnly: true, sameSite: "strict", secure: secureCookies(), path: "/", maxAge: sessionSeconds });
  return response;
}

export function DELETE(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  const response = NextResponse.json({ authenticated: false });
  response.cookies.set(sessionName, "", { httpOnly: true, sameSite: "strict", secure: secureCookies(), path: "/", maxAge: 0 });
  return response;
}
