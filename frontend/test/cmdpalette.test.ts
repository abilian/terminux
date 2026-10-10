// @vitest-environment jsdom
// Command launcher: state-aware entries, toggle labels that name the
// action they will perform, and dispatch through the command bus.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(() => true),
  workspaceCount: 1,
  copyOnSelect: false,
  scrollbackPersist: true,
}));
vi.mock("../src/input/commands", () => ({ invoke: mocks.invoke }));
vi.mock("../src/state/store", () => ({
  getState: () => ({
    workspaces: Array.from({ length: mocks.workspaceCount }, (_, i) => ({
      id: `w${i}`,
      name: `ws${i}`,
      tab_ids: [],
      active_tab_id: null,
      status: "idle",
      active_seconds: 0,
    })),
    tabs: {},
    active_workspace_id: "w0",
    ui: {
      copy_on_select: mocks.copyOnSelect,
      scrollback_persist: mocks.scrollbackPersist,
    },
  }),
  activeSession: () => null,
}));

type CmdPalette = typeof import("../src/ui/cmdpalette");
let cmdpalette: CmdPalette;

function labels(): string[] {
  return [...document.querySelectorAll(".pal-row")].map(
    (r) => r.textContent ?? "",
  );
}

beforeEach(async () => {
  vi.resetModules();
  document.body.innerHTML = "";
  cmdpalette = await import("../src/ui/cmdpalette");
  mocks.invoke.mockClear();
  mocks.workspaceCount = 1;
  mocks.copyOnSelect = false;
  mocks.scrollbackPersist = true;
});

describe("command launcher", () => {
  it("hides both sidebar sorts until a second workspace exists", () => {
    const sorts = (): string[] =>
      labels().filter((l) => l.startsWith("Sort by"));
    cmdpalette.openCmdPalette();
    expect(sorts()).toEqual([]);
    mocks.workspaceCount = 2;
    cmdpalette.openCmdPalette();
    expect(sorts()).toEqual([
      "Sort by recent activity (ready, working, then last used)",
      "Sort by time spent (most used first)",
    ]);
  });

  it("lists the remote-connection command", () => {
    cmdpalette.openCmdPalette();
    expect(labels()).toContain("Show remote connection URL");
  });

  it("toggle labels name the action that will run", () => {
    cmdpalette.openCmdPalette();
    expect(labels()).toContain("Enable auto-copy on selection");
    expect(labels()).toContain("Disable scrollback persistence");
    mocks.copyOnSelect = true;
    mocks.scrollbackPersist = false;
    cmdpalette.openCmdPalette();
    expect(labels()).toContain("Disable auto-copy on selection");
    expect(labels()).toContain("Enable scrollback persistence");
  });

  it("Enter dispatches the selected command and closes", async () => {
    cmdpalette.openCmdPalette();
    const input =
      document.querySelector<HTMLInputElement>("#cmdpalette input")!;
    input.value = "usage";
    input.dispatchEvent(new Event("input"));
    await new Promise((r) => setTimeout(r, 0)); // flush the filter render
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    expect(mocks.invoke).toHaveBeenCalledWith("view.stats");
    expect(document.getElementById("cmdpalette")!.hidden).toBe(true);
  });
});
