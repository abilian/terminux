// The two sidebar sorts: time spent (most used first), and recent
// activity (ready first-come first-served, then working, then by when the
// user last typed there).

import { describe, expect, it } from "vitest";

import { byRecentActivity, byTimeSpent } from "../src/state/sorting";
import type { WorkspaceView } from "../src/state/types";

function ws(id: string, fields: Partial<WorkspaceView> = {}): WorkspaceView {
  return {
    id,
    name: id,
    tab_ids: [],
    active_tab_id: null,
    status: "idle",
    active_seconds: 0,
    last_used_at: null,
    ready_since: null,
    ...fields,
  };
}

const ids = (list: WorkspaceView[]): string[] => list.map((w) => w.id);

describe("sidebar sorts", () => {
  it("sorts by time spent, most used first", () => {
    const list = [
      ws("a", { active_seconds: 5 }),
      ws("b", { active_seconds: 50 }),
      ws("c", { active_seconds: 20 }),
    ];
    expect(ids(byTimeSpent(list))).toEqual(["b", "c", "a"]);
  });

  it("puts ready workspaces first, oldest ready first", () => {
    const list = [
      ws("idle", { last_used_at: 900 }),
      ws("late", { status: "unseen", ready_since: 300, last_used_at: 999 }),
      ws("early", { status: "unseen", ready_since: 100, last_used_at: 1 }),
    ];
    expect(ids(byRecentActivity(list))).toEqual(["early", "late", "idle"]);
  });

  it("puts working workspaces after ready ones, then the rest by last use", () => {
    const list = [
      ws("old", { last_used_at: 100 }),
      ws("never"),
      ws("working-old", { status: "busy", last_used_at: 50 }),
      ws("recent", { status: "active", last_used_at: 500 }),
      ws("ready", { status: "unseen", ready_since: 10 }),
      ws("working-new", { status: "busy", last_used_at: 400 }),
    ];
    expect(ids(byRecentActivity(list))).toEqual([
      "ready",
      "working-new",
      "working-old",
      "recent",
      "old",
      "never",
    ]);
  });

  it("does not change the input list", () => {
    const list = [ws("a", { last_used_at: 1 }), ws("b", { last_used_at: 2 })];
    byRecentActivity(list);
    expect(ids(list)).toEqual(["a", "b"]);
  });
});
