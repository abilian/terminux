// Token-guarded fetch wrapper for the loopback control plane.

export const TOKEN: string = window.TERMINUX_TOKEN;

/**
 * Send a change to the backend. A refused request is logged; the next poll
 * shows what the backend really holds.
 */
export async function send(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: object,
): Promise<void> {
  const r = await api(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    console.error(`${method} /api${path}: HTTP ${r.status}`);
  }
}

export function api(path: string, opts: RequestInit = {}): Promise<Response> {
  const sep = path.includes("?") ? "&" : "?";
  return fetch(`/api${path}${sep}t=${TOKEN}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
}
