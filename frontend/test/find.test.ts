// @vitest-environment jsdom
// Find-in-terminal overlay: incremental search while typing, Enter /
// Shift+Enter stepping, Escape returning focus to the terminal.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  session: {
    search: { findNext: vi.fn(), findPrevious: vi.fn() },
    term: { focus: vi.fn() },
  },
}));
vi.mock("../src/state/store", () => ({
  activeSession: () => mocks.session,
}));

type Find = typeof import("../src/ui/find");
let find: Find;
let input: HTMLInputElement;

beforeEach(async () => {
  vi.resetModules();
  document.body.innerHTML = "";
  find = await import("../src/ui/find");
  mocks.session.search.findNext.mockClear();
  mocks.session.search.findPrevious.mockClear();
  mocks.session.term.focus.mockClear();
  find.openFind();
  input = document.querySelector<HTMLInputElement>("#find input")!;
});

describe("find overlay", () => {
  it("searches incrementally while typing", () => {
    input.value = "err";
    input.dispatchEvent(new Event("input"));
    expect(mocks.session.search.findNext).toHaveBeenCalledWith("err", {
      incremental: true,
    });
  });

  it("Enter steps forward, Shift+Enter steps back", () => {
    input.value = "err";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    expect(mocks.session.search.findNext).toHaveBeenCalledWith("err");
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", shiftKey: true }),
    );
    expect(mocks.session.search.findPrevious).toHaveBeenCalledWith("err");
  });

  it("Escape closes and hands focus back to the terminal", () => {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(document.getElementById("find")!.hidden).toBe(true);
    expect(mocks.session.term.focus).toHaveBeenCalled();
  });
});
