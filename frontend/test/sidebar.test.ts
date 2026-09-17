// @vitest-environment jsdom
// Island-level tests for the sidebar: rendering from state, and the
// property the Preact migration exists for — a rename in progress
// survives re-renders (the 2 s poll) because the DOM is diffed.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StateView } from "../src/state/types";

const apiMock = vi.fn(() => Promise.resolve({}));
let fakeState: StateView | null = null;

vi.mock("../src/state/api", () => ({
  api: (...args: unknown[]) => apiMock(...args),
  TOKEN: "t",
}));
vi.mock("../src/state/store", () => ({
  getState: () => fakeState,
  refresh: vi.fn(() => Promise.resolve()),
  setActiveWorkspaceOptimistic: vi.fn(() => Promise.resolve()),
}));
// terminal.ts drags in xterm; the sidebar only needs disposeSession.
vi.mock("../src/term/terminal", () => ({ disposeSession: vi.fn() }));

const { renderSidebar } = await import("../src/ui/sidebar");

function state(): StateView {
  return {
    workspaces: [
      {
        id: "w1",
        name: "alpha",
        tab_ids: ["t1"],
        active_tab_id: "t1",
        status: "active",
        active_seconds: 0,
      },
      {
        id: "w2",
        name: "beta",
        tab_ids: ["t2"],
        active_tab_id: "t2",
        status: "busy",
        active_seconds: 95,
      },
    ],
    tabs: {},
    active_workspace_id: "w1",
    session_started_at: 0,
    ui: {
      sidebar_width: 220,
      sidebar_collapsed: false,
      font_size: 13,
      copy_on_select: false,
      scrollback_persist: true,
    },
  };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

async function dbl(el: Element): Promise<void> {
  el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
  await tick(); // Preact flushes hook-state renders on a microtask
}

beforeEach(() => {
  document.body.innerHTML = '<div id="ws-list"></div>';
  fakeState = state();
  apiMock.mockClear();
});

describe("sidebar island", () => {
  it("renders one row per workspace with keycap, dot, and time", () => {
    renderSidebar();
    const rows = document.querySelectorAll(".ws-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].classList.contains("active")).toBe(true);
    expect(rows[0].querySelector(".slot.keycap")?.textContent).toBe("1");
    expect(rows[1].querySelector(".dot.busy")).toBeTruthy();
    expect(rows[1].querySelector(".active-time")?.textContent).toBe("1m 35s");
    // Zero active time renders no tag.
    expect(rows[0].querySelector(".active-time")).toBeNull();
  });

  it("keeps a rename in progress across re-renders", async () => {
    renderSidebar();
    await dbl(document.querySelector(".ws-row.active .name")!);
    const input = document.querySelector<HTMLInputElement>(
      ".ws-row .name-input",
    )!;
    expect(input.value).toBe("alpha");
    input.value = "alp-renamed";
    // Simulate two poll cycles (state refreshed, island re-rendered).
    fakeState = state();
    renderSidebar();
    renderSidebar();
    const after = document.querySelector<HTMLInputElement>(
      ".ws-row .name-input",
    );
    expect(after).toBe(input); // same DOM node, not a rebuild
    expect(after!.value).toBe("alp-renamed");
  });

  it("commits on Enter and cancels on Escape", async () => {
    renderSidebar();
    await dbl(document.querySelector(".ws-row.active .name")!);
    const input = document.querySelector<HTMLInputElement>(
      ".ws-row .name-input",
    )!;
    input.value = "pinned";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await tick();
    expect(apiMock).toHaveBeenCalledWith(
      "/workspaces/w1",
      expect.objectContaining({ method: "PATCH" }),
    );
    renderSidebar();
    expect(document.querySelector(".ws-row .name-input")).toBeNull();

    await dbl(document.querySelector(".ws-row.active .name")!);
    const again = document.querySelector<HTMLInputElement>(
      ".ws-row .name-input",
    )!;
    again.value = "discarded";
    apiMock.mockClear();
    again.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await tick();
    renderSidebar();
    expect(document.querySelector(".ws-row .name-input")).toBeNull();
    expect(apiMock).not.toHaveBeenCalled();
  });
});
