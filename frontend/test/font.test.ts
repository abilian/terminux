// Font zoom: one-shot adoption of the persisted size, clamped explicit
// zoom applied to every live session and PATCHed to the server.

import { beforeEach, describe, expect, it, vi } from "vitest";

interface FakeSession {
  term: { options: { fontSize?: number } };
  fit: { fit: () => void };
}

const mocks = vi.hoisted(() => ({
  api: vi.fn((..._args: unknown[]) => Promise.resolve({})),
  sessions: new Map<string, unknown>(),
  fontFromServer: 16 as number | undefined,
}));
vi.mock("../src/state/api", () => ({
  api: mocks.api,
  TOKEN: "t",
  send: (method: string, path: string, body?: object) =>
    mocks.api(path, { method, body: body && JSON.stringify(body) }),
}));
vi.mock("../src/state/store", () => ({
  sessions: mocks.sessions,
  getState: () => ({ ui: { font_size: mocks.fontFromServer } }),
}));

type Font = typeof import("../src/term/font");
let font: Font;
let sess: FakeSession;

beforeEach(async () => {
  vi.resetModules();
  font = await import("../src/term/font");
  sess = { term: { options: {} }, fit: { fit: vi.fn() } };
  mocks.sessions.clear();
  mocks.sessions.set("t1", sess);
  mocks.api.mockClear();
  mocks.fontFromServer = 16;
});

describe("font", () => {
  it("adopts the persisted size", () => {
    font.syncFontFromState();
    expect(font.getFontSize()).toBe(16);
    expect(sess.term.options.fontSize).toBe(16);
  });

  it("applies an explicit zoom, clamped, to sessions and the server", () => {
    font.applyFontSize(99);
    expect(font.getFontSize()).toBe(32); // FONT_MAX
    expect(sess.term.options.fontSize).toBe(32);
    expect(sess.fit.fit).toHaveBeenCalled();
    expect(mocks.api).toHaveBeenCalledWith(
      "/ui",
      expect.objectContaining({ body: JSON.stringify({ font_size: 32 }) }),
    );
    font.applyFontSize(1);
    expect(font.getFontSize()).toBe(6); // FONT_MIN
  });

  it("resetFontSize returns to the default", () => {
    font.applyFontSize(20);
    font.resetFontSize();
    expect(font.getFontSize()).toBe(13);
  });
});
