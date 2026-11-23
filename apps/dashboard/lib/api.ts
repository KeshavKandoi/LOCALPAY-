export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api/backend/" + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const message = { 401: "Sign in to continue.", 404: "This record could not be found.", 409: "This action conflicts with an existing record.", 422: "Check the supplied values.", 502: "Could not reach the LocalPay API.", 503: "Required services or webhook encryption are unavailable." }[response.status];
    throw new Error(message ?? "The API returned HTTP " + response.status + ".");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function post<T>(path: string, body?: unknown) {
  return api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}
