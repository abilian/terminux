// @vitest-environment jsdom
// Scrollback saves: keepalive only on the page-hide flush (browsers cap
// keepalive bodies at 64 KiB), and a failed save leaves the tab dirty so
// the next tick retries it.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../src/state/api", () => ({ api: mocks.api, TOKEN: "t" }));
vi.mock("../src/state/store", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/state/store")>()),
  getState: () => ({ ui: { scrollback_persist: true } }),
}));
// terminal.ts pulls in xterm and its addons; none are used by a flush.
vi.mock("@xterm/xterm", () => ({ Terminal: class {} }));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: class {} }));
vi.mock("@xterm/addon-search", () => ({ SearchAddon: class {} }));
vi.mock("@xterm/addon-serialize", () => ({ SerializeAddon: class {} }));
vi.mock("@xterm/addon-web-links", () => ({ WebLinksAddon: class {} }));

const { flushScrollback } = await import("../src/term/terminal");
const { sessions } = await import("../src/state/store");

function addSession(tid: string, dirty: boolean): { dirty: boolean } {
  const sess = {
    dirty,
    term: { cols: 80, rows: 24 },
    serialize: { serialize: () => "output" },
  };
  sessions.set(tid, sess as never);
  return sess;
}

function keepaliveFlags(): unknown[] {
  return mocks.api.mock.calls.map(
    (c: unknown[]) => (c[1] as { keepalive: boolean }).keepalive,
  );
}

const settle = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  sessions.clear();
  mocks.api.mockReset();
  mocks.api.mockResolvedValue({ ok: true });
});

describe("scrollback saves", () => {
  it("sends only dirty tabs, with keepalive only on the final flush", async () => {
    addSession("t1", true);
    addSession("t2", false);
    flushScrollback();
    await settle();
    expect(mocks.api.mock.calls.map((c: unknown[]) => c[0])).toEqual([
      "/tabs/t1/scrollback",
    ]);
    expect(keepaliveFlags()).toEqual([false]);

    mocks.api.mockClear();
    addSession("t3", true);
    flushScrollback(true);
    expect(keepaliveFlags()).toEqual([true]);
  });

  it("keeps a tab dirty when its save fails", async () => {
    const rejected = addSession("t1", true);
    const refused = addSession("t2", true);
    const saved = addSession("t3", true);
    mocks.api
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true });
    flushScrollback();
    await settle();
    expect([rejected.dirty, refused.dirty, saved.dirty]).toEqual([
      true,
      true,
      false,
    ]);
  });
});
