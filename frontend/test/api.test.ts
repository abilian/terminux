// @vitest-environment jsdom
// The token-appending fetch wrapper: every control-plane call carries
// ?t=<token> with the right separator, and options pass through.

import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchSpy = vi.fn(() => Promise.resolve(new Response("{}")));

type Api = typeof import("../src/state/api");
let api: Api["api"];

beforeEach(async () => {
  vi.resetModules();
  window.TERMINUX_TOKEN = "abc-def-ghi";
  vi.stubGlobal("fetch", fetchSpy);
  fetchSpy.mockClear();
  api = (await import("../src/state/api")).api;
});

describe("api", () => {
  it("appends the token with ? on bare paths and & on queries", async () => {
    await api("/state");
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/state?t=abc-def-ghi",
      expect.anything(),
    );
    await api("/tabs/t1/scrollback?v=2");
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/tabs/t1/scrollback?v=2&t=abc-def-ghi",
      expect.anything(),
    );
  });

  it("defaults to JSON and lets options override and extend", async () => {
    await api("/ui", { method: "PATCH", keepalive: true });
    const init = fetchSpy.mock.calls.at(-1)?.[1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(init.keepalive).toBe(true);
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });
});
