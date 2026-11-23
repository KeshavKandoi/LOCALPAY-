import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const sessionName = "localpay_dashboard";
export const sessionSeconds = 8 * 60 * 60;

function equal(first: string, second: string): boolean {
  const left = Buffer.from(first);
  const right = Buffer.from(second);
  return left.length === right.length && timingSafeEqual(left, right);
}

export function tokenMatches(input: string): boolean {
  const token = process.env.LOCALPAY_ADMIN_TOKEN;
  return !!token && equal(input, token);
}

function signature(payload: string, token: string): string {
  return createHmac("sha256", token).update("localpay-dashboard:").update(payload).digest("hex");
}

export function newSession(): string {
  const token = process.env.LOCALPAY_ADMIN_TOKEN;
  if (!token) throw new Error("Dashboard administration is disabled");
  const payload = [Math.floor(Date.now() / 1000) + sessionSeconds, randomBytes(16).toString("hex")].join(".");
  return [payload, signature(payload, token)].join(".");
}

export function validSession(cookie: string | undefined): boolean {
  const token = process.env.LOCALPAY_ADMIN_TOKEN;
  if (!token || !cookie || !/^\d{10,}[.][0-9a-f]{32}[.][0-9a-f]{64}$/.test(cookie)) return false;
  const [expiry, nonce, hash] = cookie.split(".");
  return Number(expiry) > Date.now() / 1000 && equal(hash, signature([expiry, nonce].join("."), token));
}

export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;
  try {
    const address = new URL(origin);
    return address.host === host && ["http:", "https:"].includes(address.protocol);
  } catch {
    return false;
  }
}

export function secureCookies(): boolean {
  return process.env.LOCALPAY_DASHBOARD_SECURE_COOKIE === "true";
}
