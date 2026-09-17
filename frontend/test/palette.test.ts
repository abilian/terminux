// @vitest-environment jsdom
// Quick switcher: entries from state, fuzzy filtering, keyboard
// navigation, and activation via Enter.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  api: vi.fn(() => Promise.resolve({})),
}));
vi.mock("../src/state/api", () => ({ api: mocks.api, TOKEN: "t" }));
vi.mock("../src/state/store", () => ({
  getState: () => ({
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
        status: "idle",
        active_seconds: 0,
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
        live: true,
        has_unseen_output: false,
      },
    },
    active_workspace_id: "w1",
  }),
  activeSession: () => null,
  refresh: vi.fn(() => Promise.resolve()),
}));

type Palette = typeof import("../src/ui/palette");
let palette: Palette;

function key(name: string): void {
  document
    .querySelector("#palette input")!
    .dispatchEvent(new KeyboardEvent("keydown", { key: name }));
}

beforeEach(async () => {
  vi.resetModules();
  document.body.innerHTML = "";
  palette = await import("../src/ui/palette");
  mocks.api.mockClear();
});

describe("quick switcher", () => {
  it("lists every workspace and tab on open", () => {
    palette.openPalette();
    const rows = document.querySelectorAll(".pal-row");
    // 2 workspaces + 2 tabs.
    expect(rows).toHaveLength(4);
    expect(document.getElementById("palette")!.hidden).toBe(false);
    expect(rows[0].classList.contains("sel")).toBe(true);
  });

  it("filters with fuzzy match and clears on no hit", () => {
    palette.openPalette();
    const input = document.querySelector<HTMLInputElement>("#palette input")!;
    input.value = "beta";
    input.dispatchEvent(new Event("input"));
    const rows = [...document.querySelectorAll(".pal-row")];
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((r) => r.textContent!.includes("beta"))).toBe(true);
    input.value = "zzqqxx";
    input.dispatchEvent(new Event("input"));
    expect(document.querySelectorAll(".pal-row")).toHaveLength(0);
  });

  it("ArrowDown + Enter activates the selected entry and closes", () => {
    palette.openPalette();
    key("ArrowDown");
    expect(
      document.querySelectorAll(".pal-row")[1].classList.contains("sel"),
    ).toBe(true);
    key("Enter");
    expect(mocks.api).toHaveBeenCalledWith(
      "/workspaces/w1",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(document.getElementById("palette")!.hidden).toBe(true);
  });

  it("Escape closes without activating anything", () => {
    palette.openPalette();
    key("Escape");
    expect(document.getElementById("palette")!.hidden).toBe(true);
    expect(mocks.api).not.toHaveBeenCalled();
  });
});
