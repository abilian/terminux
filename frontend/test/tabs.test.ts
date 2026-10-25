// @vitest-environment jsdom
// Island-level tests for the tab bar: tabs from state, and the workspace
// chip that stands in for a hidden sidebar.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StateView } from "../src/state/types";

const apiMock = vi.fn((..._args: unknown[]) => Promise.resolve({}));
let fakeState: StateView | null = null;

vi.mock("../src/state/api", () => ({
  api: (...args: unknown[]) => apiMock(...args),
  TOKEN: "t",
  send: (...args: Parameters<typeof send>) => send(...args),
}));
// ``send`` and ``mutate`` as the app does them, through the mocked ``api``.
const send = (method: string, path: string, body?: object) =>
  apiMock(path, { method, body: body && JSON.stringify(body) });
const mutate = send;
vi.mock("../src/state/store", () => ({
  getState: () => fakeState,
  activeWorkspace: () =>
    fakeState?.workspaces.find(
      (w) => w.id === fakeState?.active_workspace_id,
    ) ?? null,
  refresh: vi.fn(() => Promise.resolve()),
  mutate: (...args: Parameters<typeof mutate>) => mutate(...args),
  setActiveTabOptimistic: vi.fn(() => Promise.resolve()),
}));
vi.mock("../src/term/terminal", () => ({ disposeSession: vi.fn() }));

const { renderTabs, closeTab, switchTab } = await import("../src/ui/tabs");
const storeMod = await import("../src/state/store");
const termMod = await import("../src/term/terminal");
const tick = () => new Promise((r) => setTimeout(r, 0));

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
        last_used_at: null,
        ready_since: null,
      },
    ],
    tabs: {
      t1: {
        id: "t1",
        title: "vim",
        user_set_title: false,
        live: true,
        has_unseen_output: false,
      },
      t2: {
        id: "t2",
        title: "make",
        user_set_title: false,
        live: false,
        has_unseen_output: true,
      },
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
  vi.mocked(storeMod.setActiveTabOptimistic).mockClear();
  vi.mocked(termMod.disposeSession).mockClear();
});

describe("tab bar island", () => {
  it("renders tabs with active state, exited suffix, and activity dot", () => {
    renderTabs();
    const tabs = document.querySelectorAll(".tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0].classList.contains("active")).toBe(true);
    expect(tabs[1].querySelector(".title")?.textContent).toBe("make (exited)");
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
    expect(document.getElementById("sidebar")!.style.display).not.toBe("none");
    expect(document.querySelector("#ws-chip")).toBeNull();
  });

  it("clicking an inactive tab switches; its ✕ closes it", () => {
    renderTabs();
    const second = document.querySelectorAll(".tab")[1] as HTMLElement;
    second.click();
    expect(storeMod.setActiveTabOptimistic).toHaveBeenCalledWith("w1", "t2");
    (second.querySelector(".x") as HTMLElement).click();
    expect(termMod.disposeSession).toHaveBeenCalledWith("t2");
    expect(apiMock).toHaveBeenCalledWith(
      "/tabs/t2",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("switchTab steps through the list with wraparound", () => {
    switchTab(1);
    expect(storeMod.setActiveTabOptimistic).toHaveBeenLastCalledWith(
      "w1",
      "t2",
    );
    switchTab(-1); // from t1, backwards wraps to the end
    expect(storeMod.setActiveTabOptimistic).toHaveBeenLastCalledWith(
      "w1",
      "t2",
    );
  });

  it("closeTab disposes the session before deleting the tab", () => {
    closeTab("t1");
    expect(termMod.disposeSession).toHaveBeenCalledWith("t1");
    expect(apiMock).toHaveBeenCalledWith(
      "/tabs/t1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("a tab rename survives a re-render and commits on Enter", async () => {
    renderTabs();
    document
      .querySelectorAll(".tab")[1]
      .querySelector(".title")!
      .dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    await tick();
    const input = document.querySelector<HTMLInputElement>(".tab .name-input")!;
    expect(input.value).toBe("make");
    input.value = "build";
    renderTabs(); // a poll re-render must not touch the typed value
    expect(
      document.querySelector<HTMLInputElement>(".tab .name-input")!.value,
    ).toBe("build");
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    await tick();
    expect(apiMock).toHaveBeenCalledWith(
      "/tabs/t2",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});
