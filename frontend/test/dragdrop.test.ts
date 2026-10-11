// @vitest-environment jsdom
// Dropped text goes in as a paste (claim + bracketed paste); dropped
// files are left to the native handler.

import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ pasteText: vi.fn(), focus: vi.fn() }));
vi.mock("../src/term/clipboard", () => ({ pasteText: mocks.pasteText }));
vi.mock("../src/state/store", () => ({
  activeSession: () => ({ term: { focus: mocks.focus } }),
}));

const { installDragAndDrop } = await import("../src/ui/dragdrop");
installDragAndDrop();

function drop(dataTransfer: unknown): void {
  const e = new Event("drop", { cancelable: true });
  Object.defineProperty(e, "dataTransfer", { value: dataTransfer });
  window.dispatchEvent(e);
}

describe("drag and drop", () => {
  it("pastes dropped text into the active terminal", () => {
    drop({ files: [], getData: () => "echo hi" });
    expect(mocks.pasteText).toHaveBeenCalledWith("echo hi");
    expect(mocks.focus).toHaveBeenCalled();
  });

  it("leaves dropped files to the native handler", () => {
    mocks.pasteText.mockClear();
    drop({ files: [{}], getData: () => "/tmp/x" });
    expect(mocks.pasteText).not.toHaveBeenCalled();
  });
});
