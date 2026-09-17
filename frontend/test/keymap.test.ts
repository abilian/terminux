// @vitest-environment jsdom
// Global shortcuts: physical chords map to command ids through the bus,
// and only handled chords are swallowed. Platform is mocked to Linux
// (Ctrl+Shift app modifier); the mac differences live in platform.ts.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ invoke: vi.fn(() => true) }));
vi.mock("../src/input/commands", () => ({ invoke: mocks.invoke }));
vi.mock("../src/input/platform", () => ({
  IS_MAC: false,
  appMod: (e: KeyboardEvent | MouseEvent) => e.ctrlKey && e.shiftKey,
}));

function press(init: KeyboardEventInit): KeyboardEvent {
  const e = new KeyboardEvent("keydown", { cancelable: true, ...init });
  window.dispatchEvent(e);
  return e;
}

// Installed once: installShortcuts adds a window listener, and repeating
// it per test would stack listeners (a chord would then be handled twice).
const { installShortcuts } = await import("../src/input/keymap");
installShortcuts();

beforeEach(() => {
  mocks.invoke.mockClear();
});

describe("keymap (Linux conventions)", () => {
  it("maps app chords to commands and swallows the event", () => {
    const e = press({ code: "KeyT", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("tab.new");
    expect(e.defaultPrevented).toBe(true);
    press({ code: "Digit3", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("workspace.jump.3");
    press({ code: "ArrowUp", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("workspace.prev");
  });

  it("opens the command palette on bare F1", () => {
    const e = press({ key: "F1" });
    expect(mocks.invoke).toHaveBeenCalledWith("palette.command");
    expect(e.defaultPrevented).toBe(true);
  });

  it("lets unmodified keys flow to the shell", () => {
    const e = press({ code: "KeyT" });
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(e.defaultPrevented).toBe(false);
  });

  it("does not swallow a chord the bus rejects", () => {
    mocks.invoke.mockReturnValueOnce(false);
    const e = press({ code: "KeyB", ctrlKey: true, shiftKey: true });
    expect(e.defaultPrevented).toBe(false);
  });
});
