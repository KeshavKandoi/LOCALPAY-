import { BodyTooLarge, boundedBody } from "@/lib/request";
import { NextRequest, NextResponse } from "next/server";
import { accountRequest, sameOrigin, secureCookies, sessionName, sessionSeconds, validSessionToken } from "@/lib/session";

function json(body: object, status = 200, retry?: string | null) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store", ...(retry ? { "Retry-After": retry } : {}) } });
}

function setCookie(request: Request, response: NextResponse, value: string) {
  response.cookies.set(sessionName, value, { httpOnly: true, sameSite: "strict", secure: secureCookies(request), path: "/", maxAge: value ? sessionSeconds : 0 });
  return response;
}

export async function GET(request: NextRequest) {
  const token = request.cookies.get(sessionName)?.value;
  if (!validSessionToken(token)) return json({ authenticated: false });
  try {
    const upstream = await accountRequest("session", token);
    if (upstream.status === 401) return setCookie(request, json({ authenticated: false }), "");
    if (!upstream.ok) return json({ error: "Session service unavailable." }, 503);
    const { username } = await upstream.json();
    return json({ authenticated: true, username });
  } catch {
    return json({ error: "Session service unavailable." }, 503);
  }
}

async function change(request: NextRequest) {
  if (!sameOrigin(request)) return json({ error: "Invalid origin." }, 403);
  const token = request.cookies.get(sessionName)?.value;
  const action = request.nextUrl.searchParams.get("action");
  const registering = request.method === "POST" && action === "signup";
  const path = request.method === "POST" ? registering ? "signup" : "login"
    : request.method === "PATCH" ? "password" : action === "others" ? "other-sessions" : "session";
  if (request.method !== "POST" && !validSessionToken(token)) {
    if (request.method === "DELETE" && action !== "others") return setCookie(request, json({ authenticated: false }), "");
    return json({ error: "Sign in to continue." }, 401);
  }
  try {
    const body = request.method === "DELETE" ? undefined : await boundedBody(request, 4096);
    const upstream = await accountRequest(path, request.method === "POST" ? undefined : token, { method: request.method, body });
    if (!upstream.ok) {
      const message = upstream.status === 429 ? "Too many attempts. Try again shortly."
        : upstream.status === 409 ? "Could not register with those details."
        : upstream.status === 422 ? "Check the username and password requirements and confirm the passwords match."
        : upstream.status === 403 ? "Incorrect current password."
        : upstream.status === 401 ? request.method === "POST" ? "Incorrect username or password." : "Sign in to continue."
        : "Account service unavailable.";
      return json({ error: message }, upstream.status, upstream.headers.get("Retry-After"));
    }
    if (request.method === "DELETE") {
      return action === "others" ? json({ revoked: true }) : setCookie(request, json({ authenticated: false }), "");
    }
    const result = await upstream.json();
    if (request.method === "PATCH") return json({ username: result.username });
    if (!validSessionToken(result.token)) return json({ error: "Account service unavailable." }, 502);
    return setCookie(request, json({ authenticated: true, username: result.username }, registering ? 201 : 200), result.token);
  } catch (error) {
    if (error instanceof BodyTooLarge) return json({ error: "Request too large." }, 413);
    return json({ error: "Account service unavailable." }, 503);
  }
}

export { change as POST, change as PATCH, change as DELETE };
