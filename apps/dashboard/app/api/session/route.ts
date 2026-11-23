import { NextRequest, NextResponse } from "next/server";
import { newSession, sameOrigin, secureCookies, sessionName, sessionSeconds, tokenMatches, validSession } from "@/lib/session";

export function GET(request: NextRequest) {
  return NextResponse.json({ authenticated: validSession(request.cookies.get(sessionName)?.value) }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  let body: { token?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
  if (!body || typeof body.token !== "string" || !tokenMatches(body.token)) {
    return NextResponse.json({ error: "Invalid administration token" }, { status: 401 });
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
