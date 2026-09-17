// @vitest-environment jsdom
// Island-level tests for the tab bar: tabs from state, and the workspace
// chip that stands in for a hidden sidebar.

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
  activeWorkspace: () =>
    fakeState?.workspaces.find(
      (w) => w.id === fakeState?.active_workspace_id,
    ) ?? null,
  refresh: vi.fn(() => Promise.resolve()),
  setActiveTabOptimistic: vi.fn(() => Promise.resolve()),
}));
vi.mock("../src/term/terminal", () => ({ disposeSession: vi.fn() }));

const { renderTabs } = await import("../src/ui/tabs");

function state(): StateView {
  return {
    workspaces: [
      {
        id: "w1",
        name: "alpha",
        tab_ids: ["t1", "t2"],
        active_tab_id: "t1",
        status: "active",
        active_seconds: 0,
      },
    ],
    tabs: {
      t1: { id: "t1", title: "vim", user_set_title: false, live: true, has_unseen_output: false },
      t2: { id: "t2", title: "make", user_set_title: false, live: false, has_unseen_output: true },
    },
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

beforeEach(() => {
  document.body.innerHTML =
    '<aside id="sidebar"></aside><div id="tabbar"></div>';
  fakeState = state();
  apiMock.mockClear();
});

describe("tab bar island", () => {
  it("renders tabs with active state, exited suffix, and activity dot", () => {
    renderTabs();
    const tabs = document.querySelectorAll(".tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0].classList.contains("active")).toBe(true);
    expect(tabs[1].querySelector(".title")?.textContent).toBe(
      "make (exited)",
    );
    expect(tabs[1].querySelector(".activity")).toBeTruthy();
    expect(document.querySelector("#new-tab")).toBeTruthy();
  });

  it("shows the workspace chip only while the sidebar is hidden", () => {
    renderTabs();
    expect(document.querySelector("#ws-chip")).toBeNull();
    document.getElementById("sidebar")!.style.display = "none";
    renderTabs();
    const chip = document.querySelector("#ws-chip")!;
    expect(chip.querySelector(".name")?.textContent).toBe("alpha");
    expect(chip.querySelector(".keycap")?.textContent).toBe("1");
    expect(chip.querySelector(".dot.active")).toBeTruthy();
  });

  it("clicking the chip restores the sidebar and drops the chip", () => {
    document.getElementById("sidebar")!.style.display = "none";
    renderTabs();
    (document.querySelector("#ws-chip") as HTMLElement).click();
    expect(document.getElementById("sidebar")!.style.display).not.toBe(
      "none",
    );
    expect(document.querySelector("#ws-chip")).toBeNull();
  });
});
