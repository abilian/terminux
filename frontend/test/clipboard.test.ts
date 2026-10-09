// @vitest-environment jsdom
// Copy/paste for Windows and Linux: copy writes the selection, paste goes
// through the webview's native paste when it happens and falls back to
// the clipboard API when it doesn't.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const term = {
  getSelection: vi.fn(() => "selected"),
  clearSelection: vi.fn(),
  selectAll: vi.fn(),
  paste: vi.fn(),
  focus: vi.fn(),
};
const mocks = vi.hoisted(() => ({ claim: vi.fn() }));
vi.mock("../src/state/store", () => ({ activeSession: () => ({ term }) }));
vi.mock("../src/term/terminal", () => ({ claim: mocks.claim }));

const { copySelection, expectNativePaste, pasteFromClipboard, selectAll } =
  await import("../src/term/clipboard");

const clipboard = {
  writeText: vi.fn(() => Promise.resolve()),
  readText: vi.fn(() => Promise.resolve("from clipboard")),
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(navigator, "clipboard", {
    value: clipboard,
    configurable: true,
  });
  document.execCommand = vi.fn(() => false);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("clipboard", () => {
  it("copies the selection and clears it", () => {
    expect(copySelection()).toBe(true);
    expect(clipboard.writeText).toHaveBeenCalledWith("selected");
    expect(term.clearSelection).toHaveBeenCalled();
  });

  it("declines to copy when nothing is selected", () => {
    term.getSelection.mockReturnValueOnce("");
    expect(copySelection()).toBe(false);
    expect(clipboard.writeText).not.toHaveBeenCalled();
  });

  it("selects the whole terminal", () => {
    selectAll();
    expect(term.selectAll).toHaveBeenCalled();
  });

  it("pastes the clipboard text as a paste, claiming the terminal", async () => {
    pasteFromClipboard();
    await vi.waitFor(() =>
      expect(term.paste).toHaveBeenCalledWith("from clipboard"),
    );
    expect(mocks.claim).toHaveBeenCalled();
  });

  it("lets a working execCommand paste do the job", () => {
    document.execCommand = vi.fn(() => true);
    pasteFromClipboard();
    expect(clipboard.readText).not.toHaveBeenCalled();
  });

  it("does nothing more when the webview pasted natively", () => {
    vi.useFakeTimers();
    expectNativePaste();
    window.dispatchEvent(new Event("paste"));
    vi.advanceTimersByTime(200);
    expect(clipboard.readText).not.toHaveBeenCalled();
  });

  it("falls back to the clipboard when no native paste came", () => {
    vi.useFakeTimers();
    expectNativePaste();
    vi.advanceTimersByTime(200);
    expect(clipboard.readText).toHaveBeenCalled();
  });
});
