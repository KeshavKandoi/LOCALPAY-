export const sessionName = "localpay_dashboard";
export const sessionSeconds = 8 * 60 * 60;

export function validSessionToken(value: string | undefined): value is string {
  return !!value && /^lp_session_[A-Za-z0-9_-]{43}$/.test(value);
}

export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  const site = request.headers.get("sec-fetch-site");
  if (!origin || !host || (site && site !== "same-origin")) return false;
  try {
    const address = new URL(origin);
    return address.host === host && ["http:", "https:"].includes(address.protocol);
  } catch {
    return false;
  }
}

export function secureCookies(request: Request): boolean {
  return process.env.LOCALPAY_DASHBOARD_SECURE_COOKIE === "true" ||
    request.headers.get("origin")?.startsWith("https://") === true;
}

export function accountRequest(path: string, token?: string, init?: RequestInit) {
  return fetch(new URL("/localpay/account/v1/" + path, process.env.LOCALPAY_API_URL ?? "http://127.0.0.1:8000"), {
    ...init, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) },
  });
}
