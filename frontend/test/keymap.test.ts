// @vitest-environment jsdom
// Global shortcuts: physical chords map to command ids through the bus,
// and only handled chords are swallowed. Platform is mocked to Linux
// (Ctrl+Shift app modifier); the mac differences live in platform.ts.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(() => true),
  browser: false,
}));
vi.mock("../src/input/commands", () => ({ invoke: mocks.invoke }));
vi.mock("../src/input/platform", () => ({
  IS_MAC: false,
  appMod: (e: KeyboardEvent | MouseEvent) => e.ctrlKey && e.shiftKey,
  inBrowser: () => mocks.browser,
  browserMod: (e: KeyboardEvent) =>
    mocks.browser && e.altKey && e.shiftKey && !e.ctrlKey,
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
  mocks.browser = false;
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

  it("opens the command palette on Ctrl+Shift+P, the switcher on Ctrl+Shift+O", () => {
    press({ code: "KeyP", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("palette.command");
    press({ code: "KeyO", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("palette.quick");
  });

  it("lets unmodified keys flow to the shell", () => {
    const e = press({ code: "KeyT" });
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(e.defaultPrevented).toBe(false);
  });

  it("zooms with bare Ctrl as well as Ctrl+Shift", () => {
    press({ key: "=", code: "Equal", ctrlKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("view.zoom.in");
    press({ key: "-", code: "Minus", ctrlKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("view.zoom.out");
    press({ key: "0", code: "Digit0", ctrlKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("view.zoom.reset");
    press({ key: "+", code: "Equal", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("view.zoom.in");
    press({ key: "_", code: "Minus", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("view.zoom.out");
  });

  it("zooms on the typed character, whatever the layout", () => {
    // AZERTY: "-" is on the 6 key, and Ctrl+6 must not jump anywhere.
    const e = press({ key: "-", code: "Digit6", ctrlKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("view.zoom.out");
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
    expect(e.defaultPrevented).toBe(true);
  });

  it("leaves other bare Ctrl chords to the shell", () => {
    const e = press({ key: "n", code: "KeyN", ctrlKey: true });
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(e.defaultPrevented).toBe(false);
  });

  it("does not swallow a chord the bus rejects", () => {
    mocks.invoke.mockReturnValueOnce(false);
    const e = press({ code: "KeyB", ctrlKey: true, shiftKey: true });
    expect(e.defaultPrevented).toBe(false);
  });
});

describe("clipboard chords", () => {
  it("copies and selects all with Ctrl+Shift", () => {
    const e = press({ code: "KeyC", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("edit.copy");
    expect(e.defaultPrevented).toBe(true);
    press({ code: "KeyA", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("edit.select-all");
  });

  it("swallows Ctrl+Shift+C even with nothing selected", () => {
    mocks.invoke.mockReturnValueOnce(false);
    const e = press({ code: "KeyC", ctrlKey: true, shiftKey: true });
    expect(e.defaultPrevented).toBe(true);
  });

  it("pastes with Ctrl+Shift+V, keeping the webview's own paste", () => {
    const e = press({ code: "KeyV", ctrlKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("edit.paste.keyboard");
    expect(e.defaultPrevented).toBe(false);
  });

  it("copies with bare Ctrl+C only while text is selected", () => {
    const copied = press({ code: "KeyC", ctrlKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("edit.copy");
    expect(copied.defaultPrevented).toBe(true);
    mocks.invoke.mockReturnValueOnce(false); // nothing selected
    const interrupt = press({ code: "KeyC", ctrlKey: true });
    expect(interrupt.defaultPrevented).toBe(false);
  });

  it("pastes with bare Ctrl+V", () => {
    const e = press({ code: "KeyV", ctrlKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("edit.paste.keyboard");
    expect(e.defaultPrevented).toBe(false);
  });
});

describe("browser tabs", () => {
  it("takes Alt+Shift for the chords the browser keeps", () => {
    mocks.browser = true;
    const e = press({ code: "KeyW", altKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenCalledWith("tab.close");
    expect(e.defaultPrevented).toBe(true);
    press({ code: "KeyP", altKey: true, shiftKey: true });
    expect(mocks.invoke).toHaveBeenLastCalledWith("palette.command");
  });

  it("leaves other Alt+Shift chords to the shell (M-_, M-!...)", () => {
    mocks.browser = true;
    for (const code of ["Minus", "Digit1", "BracketLeft", "KeyB"]) {
      const e = press({ code, altKey: true, shiftKey: true });
      expect(e.defaultPrevented).toBe(false);
    }
    expect(mocks.invoke).not.toHaveBeenCalled();
  });

  it("leaves Alt+Shift to the shell in the desktop window", () => {
    const e = press({ code: "KeyW", altKey: true, shiftKey: true });
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(e.defaultPrevented).toBe(false);
  });

  it("does not toggle auto-copy on Alt+Shift+C", () => {
    mocks.browser = true;
    press({ code: "KeyC", altKey: true, shiftKey: true });
    expect(mocks.invoke).not.toHaveBeenCalled();
  });
});
