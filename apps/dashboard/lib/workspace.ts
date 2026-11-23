import { boundedBody } from "./request";

export const methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] as const;
export const formats = { none: "", json: "application/json", text: "text/plain", form: "application/x-www-form-urlencoded", xml: "application/xml", multipart: "" };
export type Draft = {
  method: typeof methods[number];
  url: string;
  query: string;
  headers: string;
  format: keyof typeof formats;
  body: string;
  checks: string;
  authenticated: boolean;
};
export const defaultDraft: Draft = { method: "GET", url: "{{base_url}}/v1/orders", query: "", headers: "", format: "none", body: "", checks: "status = 200", authenticated: true };

export function pairs(input: string, separator = "="): [string, string][] {
  return input.split("\n").filter((line) => line.trim()).map((line) => {
    const index = line.indexOf(separator);
    if (index < 1) throw new Error("Expected one name " + separator + " value pair per line.");
    const name = line.slice(0, index).trim();
    if (!name) throw new Error("Each field needs a name.");
    return [name, line.slice(index + 1).trim()];
  });
}

export function prepare(draft: Draft, project: string, variables: string, secrets: string, key: string, secret: string, file: File | null) {
  const values = new Map([["base_url", location.origin], ...pairs(variables), ...pairs(secrets), ["project_id", project], ["key_id", key], ["key_secret", secret]]);
  const expand = (value: string) => value.replace(/{{([\w.-]+)}}/g, (_, name: string) => {
    const result = values.get(name);
    if (result === undefined) throw new Error("Missing variable " + name + ".");
    return result;
  });
  const url = new URL(expand(draft.url), location.origin);
  if (url.origin !== location.origin || url.username || url.password || url.hash) {
    throw new Error("Use a LocalPay API path or a URL on this dashboard origin.");
  }
  for (const [name, value] of pairs(expand(draft.query))) url.searchParams.append(name, value);
  const headers = new Headers(pairs(expand(draft.headers), ":"));
  headers.delete("authorization");
  headers.set("x-localpay-workspace-project", project);
  if (draft.authenticated && key && secret) {
    headers.set("authorization", "Basic " + btoa(key + ":" + secret));
  }
  const canSend = draft.method !== "GET" && draft.method !== "HEAD" && draft.method !== "OPTIONS";
  let body: BodyInit | undefined;
  if (canSend) {
    if (file) {
      body = file;
      headers.set("content-type", file.type || "application/octet-stream");
    } else if (draft.format !== "none") {
      const input = expand(draft.body);
      const contentType = formats[draft.format];
      if (contentType) headers.set("content-type", contentType);
      if (draft.format === "json") JSON.parse(input);
      if (draft.format === "form") body = new URLSearchParams(pairs(input));
      else if (draft.format === "multipart") {
        const form = new FormData();
        for (const [name, value] of pairs(input)) form.append(name, value);
        headers.delete("content-type");
        body = form;
      } else body = input;
    }
  }
  return { url: "/api/workspace" + url.pathname + url.search, init: { method: draft.method, headers, body, redirect: "error", cache: "no-store" } satisfies RequestInit };
}

export async function execute(prepared: ReturnType<typeof prepare>, signal: AbortSignal) {
  const started = performance.now();
  const response = await fetch(prepared.url, { ...prepared.init, signal });
  const bytes = await boundedBody(response, 524288, true);
  const raw = new TextDecoder().decode(bytes);
  const headers = Object.fromEntries(response.headers);
  if (headers["x-localpay-content-type"]) headers["content-type"] = headers["x-localpay-content-type"];
  let json: unknown;
  try { json = JSON.parse(raw); } catch {}
  return { status: response.status, ms: Math.round(performance.now() - started), size: bytes.byteLength, raw, bytes, headers, json };
}

export type Result = Awaited<ReturnType<typeof execute>>;

export function assertResponse(result: Result, checks: string) {
  return checks.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const match = /^(status|time|header\.[\w-]+|json\.[\w.-]+)\s+(exists|<=|>=|=|<|>)(?:\s+(.+))?$/.exec(line);
    if (!match) return { line, passed: false };
    const [, field, operator, expected] = match;
    let actual: unknown;
    if (field === "status") actual = result.status;
    else if (field === "time") actual = result.ms;
    else if (field.startsWith("header.")) actual = result.headers[field.slice(7).toLowerCase()];
    else actual = field.slice(5).split(".").reduce<unknown>((value, part) =>
      value !== null && typeof value === "object" && Object.hasOwn(value, part) ? Reflect.get(value, part) : undefined, result.json);
    let target: unknown = expected;
    if (expected !== undefined) {
      try { target = JSON.parse(expected); } catch {}
    }
    let passed = false;
    if (operator === "exists") passed = actual !== undefined;
    else if (operator === "=") passed = actual !== undefined && expected !== undefined && (Object.is(actual, target) || JSON.stringify(actual) === JSON.stringify(target));
    else if (typeof actual === "number" && typeof target === "number") {
      passed = operator === "<=" ? actual <= target : operator === ">=" ? actual >= target : operator === "<" ? actual < target : actual > target;
    }
    return { line, passed };
  });
}

export function curl(draft: Draft) {
  const quote = (value: string) => "'" + value.replaceAll("'", "'\\''") + "'";
  const url = draft.url + (draft.query.trim() ? (draft.url.includes("?") ? "&" : "?") + pairs(draft.query).map(([key, value]) => encodeURIComponent(key) + "=" + encodeURIComponent(value)).join("&") : "");
  const args = ["curl", "-X", draft.method, quote(url)];
  if (draft.authenticated) args.push("--user", '"${LOCALPAY_KEY_ID}:${LOCALPAY_KEY_SECRET}"');
  for (const [name, value] of pairs(draft.headers, ":")) {
    if (!/authorization|cookie|token|secret|key/i.test(name)) args.push("-H", quote(name + ": " + value));
  }
  if (draft.format !== "none" && !["GET", "HEAD", "OPTIONS"].includes(draft.method)) {
    if (formats[draft.format]) args.push("-H", quote("Content-Type: " + formats[draft.format]));
    if (draft.format === "multipart") {
      for (const [key, value] of pairs(draft.body)) args.push("--form-string", quote(key + "=" + value));
    } else args.push("--data-binary", quote(draft.format === "form" ? new URLSearchParams(pairs(draft.body)).toString() : draft.body));
  }
  return args.join(" ");
}
