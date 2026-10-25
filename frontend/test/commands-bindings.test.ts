// @vitest-environment jsdom
// The dispatch table: every command id wired by installCommands reaches
// the right feature handler. Uses the real command bus with every
// feature module mocked, so a renamed or missing registration fails here.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StateView } from "../src/state/types";

const mocks = vi.hoisted(() => ({
  api: vi.fn((..._args: unknown[]) => Promise.resolve({})),
  refresh: vi.fn(() => Promise.resolve()),
  setActiveWorkspaceOptimistic: vi.fn(() => Promise.resolve()),
  openPalette: vi.fn(),
  openCmdPalette: vi.fn(),
  openFind: vi.fn(),
  openStatsPanel: vi.fn(),
  openConnectInfo: vi.fn(),
  toggleSidebar: vi.fn(),
  closeTab: vi.fn(),
  switchTab: vi.fn(),
  closeWorkspace: vi.fn(),
  switchWorkspace: vi.fn(),
  applyFontSize: vi.fn(),
  resetFontSize: vi.fn(),
  state: null as StateView | null,
}));

vi.mock("../src/state/api", () => ({
  api: mocks.api,
  TOKEN: "t",
  send: (method: string, path: string, body?: object) =>
    mocks.api(path, { method, body: body && JSON.stringify(body) }),
}));
vi.mock("../src/state/store", () => ({
  getState: () => mocks.state,
  activeWorkspace: () =>
    mocks.state?.workspaces.find(
      (w) => w.id === mocks.state?.active_workspace_id,
    ) ?? null,
  refresh: mocks.refresh,
  mutate: (method: string, path: string, body?: object) =>
    mocks
      .api(path, { method, body: body && JSON.stringify(body) })
      .then(mocks.refresh),
  setActiveWorkspaceOptimistic: mocks.setActiveWorkspaceOptimistic,
}));
vi.mock("../src/ui/palette", () => ({ openPalette: mocks.openPalette }));
vi.mock("../src/ui/cmdpalette", () => ({
  openCmdPalette: mocks.openCmdPalette,
}));
vi.mock("../src/ui/find", () => ({ openFind: mocks.openFind }));
vi.mock("../src/ui/statspanel", () => ({
  openStatsPanel: mocks.openStatsPanel,
}));
vi.mock("../src/ui/connectinfo", () => ({
  openConnectInfo: mocks.openConnectInfo,
}));
vi.mock("../src/ui/layout", () => ({ toggleSidebar: mocks.toggleSidebar }));
vi.mock("../src/ui/sidebar", () => ({
  closeWorkspace: mocks.closeWorkspace,
  switchWorkspace: mocks.switchWorkspace,
}));
vi.mock("../src/ui/tabs", () => ({
  closeTab: mocks.closeTab,
  switchTab: mocks.switchTab,
}));
vi.mock("../src/term/font", () => ({
  applyFontSize: mocks.applyFontSize,
  getFontSize: () => 13,
  resetFontSize: mocks.resetFontSize,
}));

const { installCommands } = await import("../src/input/commands-bindings");
const { _reset, invoke } = await import("../src/input/commands");

function ws(
  id: string,
  tabs: string[],
  seconds: number,
): StateView["workspaces"][number] {
  return {
    id,
    name: id,
    tab_ids: tabs,
    active_tab_id: tabs[0] ?? null,
    status: "idle",
    active_seconds: seconds,
    last_used_at: null,
    ready_since: null,
  };
}

function state(workspaces: StateView["workspaces"]): StateView {
  return {
    workspaces,
    tabs: {},
    active_workspace_id: workspaces[0]?.id ?? null,
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
  _reset();
  installCommands();
  mocks.state = state([ws("w1", ["t1", "t2"], 5), ws("w2", ["t3"], 50)]);
  for (const f of Object.values(mocks)) {
    if (typeof f === "function" && "mockClear" in f) {
      (f as ReturnType<typeof vi.fn>).mockClear();
    }
  }
});

describe("command dispatch table", () => {
  it("routes navigation and overlay commands", () => {
    invoke("workspace.next");
    expect(mocks.switchWorkspace).toHaveBeenCalledWith(1);
    invoke("tab.prev");
    expect(mocks.switchTab).toHaveBeenCalledWith(-1);
    invoke("workspace.jump.2");
    expect(mocks.setActiveWorkspaceOptimistic).toHaveBeenCalledWith("w2");
    invoke("palette.quick");
    expect(mocks.openPalette).toHaveBeenCalled();
    invoke("view.stats");
    expect(mocks.openStatsPanel).toHaveBeenCalled();
    invoke("view.connect-info");
    expect(mocks.openConnectInfo).toHaveBeenCalled();
  });

  it("closes the active tab, or the workspace when it is the last tab", () => {
    invoke("tab.close");
    expect(mocks.closeTab).toHaveBeenCalledWith("t1");
    mocks.state = state([ws("w1", ["t1"], 0)]);
    invoke("tab.close");
    expect(mocks.closeWorkspace).toHaveBeenCalledWith("w1");
  });

  it("zooms relative to the current size", () => {
    invoke("view.zoom.in");
    expect(mocks.applyFontSize).toHaveBeenCalledWith(14);
    invoke("view.zoom.out");
    expect(mocks.applyFontSize).toHaveBeenCalledWith(12);
    invoke("view.zoom.reset");
    expect(mocks.resetFontSize).toHaveBeenCalled();
  });

  it("toggles the sidebar", () => {
    invoke("view.sidebar.toggle");
    expect(mocks.toggleSidebar).toHaveBeenCalled();
  });

  it("pref toggles PATCH the negated value and refresh", () => {
    invoke("view.copy-on-select.toggle");
    expect(mocks.api).toHaveBeenCalledWith(
      "/ui",
      expect.objectContaining({
        body: JSON.stringify({ copy_on_select: true }),
      }),
    );
  });

  it("sort by time spent PATCHes the most-used-first order once", () => {
    mocks.state = state([
      ws("w1", ["t1"], 5),
      ws("w2", ["t2"], 50),
      ws("w3", ["t3"], 20),
    ]);
    invoke("workspace.sort.time-spent");
    expect(mocks.api).toHaveBeenCalledWith(
      "/workspaces/w2",
      expect.objectContaining({
        body: JSON.stringify({ order: ["w2", "w3", "w1"] }),
      }),
    );
    // A single workspace has nothing to sort.
    mocks.api.mockClear();
    mocks.state = state([ws("w1", ["t1"], 5)]);
    invoke("workspace.sort.time-spent");
    expect(mocks.api).not.toHaveBeenCalled();
  });

  it("sort by recent activity PATCHes ready, working, then last used", () => {
    mocks.state = state([
      { ...ws("idle", ["t1"], 0), last_used_at: 900, ready_since: null },
      {
        ...ws("working", ["t2"], 0),
        status: "busy",
        last_used_at: 5,
        ready_since: null,
      },
      {
        ...ws("ready", ["t3"], 0),
        status: "unseen",
        last_used_at: null,
        ready_since: 1,
      },
    ]);
    invoke("workspace.sort.recent");
    expect(mocks.api).toHaveBeenCalledWith(
      "/workspaces/ready",
      expect.objectContaining({
        body: JSON.stringify({ order: ["ready", "working", "idle"] }),
      }),
    );
  });

  it("exposes the bus to the native menu", () => {
    expect(window.terminux.invoke("view.find")).toBe(true);
    expect(mocks.openFind).toHaveBeenCalled();
  });
});
