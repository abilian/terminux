// Token-guarded fetch wrapper for the loopback control plane.

export const TOKEN: string = window.TERMINUX_TOKEN;

export function api(path: string, opts: RequestInit = {}): Promise<Response> {
  const sep = path.includes("?") ? "&" : "?";
  return fetch(`/api${path}${sep}t=${TOKEN}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
}
