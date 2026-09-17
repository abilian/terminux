// @vitest-environment jsdom
// Usage-stats overlay: workspaces ranked by active time with relative
// bars, session-age header, empty state, and Escape/backdrop dismissal.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  seconds: { alpha: 150, beta: 300 },
}));
vi.mock("../src/state/store", () => ({
  getState: () => ({
    workspaces: [
      {
        id: "w1",
        name: "alpha",
        tab_ids: [],
        active_tab_id: null,
        status: "idle",
        active_seconds: mocks.seconds.alpha,
      },
      {
        id: "w2",
        name: "beta",
        tab_ids: [],
        active_tab_id: null,
        status: "idle",
        active_seconds: mocks.seconds.beta,
      },
    ],
    tabs: {},
    active_workspace_id: "w1",
    // 95 s before the frozen "now" below.
    session_started_at: 1_000_000_000 - 95,
    ui: {},
  }),
  activeSession: () => null,
}));

type Stats = typeof import("../src/ui/statspanel");
let stats: Stats;

beforeEach(async () => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000_000_000);
  vi.resetModules();
  document.body.innerHTML = "";
  stats = await import("../src/ui/statspanel");
  mocks.seconds = { alpha: 150, beta: 300 };
});

afterEach(() => {
  vi.useRealTimers();
});

describe("stats overlay", () => {
  it("ranks workspaces by time with bars relative to the busiest", () => {
    stats.openStatsPanel();
    const names = [...document.querySelectorAll(".stats-name")].map(
      (n) => n.textContent,
    );
    expect(names).toEqual(["beta", "alpha"]);
    const widths = [...document.querySelectorAll(".stats-bar-fill")].map(
      (f) => (f as HTMLElement).style.width,
    );
    expect(widths).toEqual(["100%", "50%"]);
    expect(document.querySelector(".stats-meta")!.textContent).toBe(
      "session started 1m 35s ago · 7m 30s active",
    );
  });

  it("shows the empty state before any keystrokes accrue", () => {
    mocks.seconds = { alpha: 0, beta: 0 };
    stats.openStatsPanel();
    expect(document.querySelector(".stats-empty")).toBeTruthy();
    expect(document.querySelectorAll(".stats-row")).toHaveLength(0);
  });

  it("closes on Escape and on backdrop click, and only when open", () => {
    stats.openStatsPanel();
    const overlay = document.getElementById("stats-overlay")!;
    expect(overlay.hidden).toBe(false);
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", cancelable: true }),
    );
    expect(overlay.hidden).toBe(true);
    stats.openStatsPanel();
    overlay.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(overlay.hidden).toBe(true);
  });

  it("ticks live from the render hook while open, and only while open", () => {
    stats.openStatsPanel();
    expect(document.querySelector(".stats-time")!.textContent).toBe("5m 00s");
    mocks.seconds = { alpha: 150, beta: 360 };
    stats.renderStatsPanel(); // what main.ts calls on every poll
    expect(document.querySelector(".stats-time")!.textContent).toBe("6m 00s");
    stats.closeStatsPanel();
    mocks.seconds = { alpha: 150, beta: 999 };
    stats.renderStatsPanel();
    expect(document.getElementById("stats-overlay")!.hidden).toBe(true);
  });
});
