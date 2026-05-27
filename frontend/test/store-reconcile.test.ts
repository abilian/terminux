import { describe, expect, it } from "vitest";

import { reconcile } from "../src/reconcile";
import type { StateView, TabView, WorkspaceView } from "../src/types";

function ws(
  id: string,
  active_tab_id: string | null,
  tab_ids: string[] = [],
): WorkspaceView {
  return {
    id,
    name: id,
    tab_ids: tab_ids.length ? tab_ids : active_tab_id ? [active_tab_id] : [],
    active_tab_id,
    status: "idle",
    active_seconds: 0,
  };
}

function tab(id: string): TabView {
  return {
    id,
    title: id,
    user_set_title: false,
    live: true,
    has_unseen_output: false,
  };
}

function state(
  active: string | null,
  workspaces: WorkspaceView[],
  tabs: TabView[],
): StateView {
  return {
    workspaces,
    tabs: Object.fromEntries(tabs.map((t) => [t.id, t])),
    active_workspace_id: active,
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

describe("reconcile (optimistic-switch race guard)", () => {
  it("overrides a stale polled active_workspace_id with the expectation", () => {
    // Backend snapshot was generated before the PATCH landed — it
    // still shows workspace A active, but the user has already
    // optimistically switched to B.
    const s = state("A", [ws("A", "a"), ws("B", "b")], [tab("a"), tab("b")]);
    const next = reconcile(s, { ws: "B", tabs: new Map() });
    expect(s.active_workspace_id).toBe("B");
    // Expectation kept because the poll didn't confirm it.
    expect(next.ws).toBe("B");
  });

  it("clears the workspace expectation once the poll agrees", () => {
    const s = state("B", [ws("A", "a"), ws("B", "b")], [tab("a"), tab("b")]);
    const next = reconcile(s, { ws: "B", tabs: new Map() });
    expect(s.active_workspace_id).toBe("B");
    expect(next.ws).toBeNull();
  });

  it("drops the expectation if the target workspace no longer exists", () => {
    // The user switched to B optimistically, then B was deleted on
    // the backend. Don't keep forcing the UI to a phantom.
    const s = state("A", [ws("A", "a")], [tab("a")]);
    const next = reconcile(s, { ws: "B", tabs: new Map() });
    expect(s.active_workspace_id).toBe("A");
    expect(next.ws).toBeNull();
  });

  it("overrides a stale active_tab_id within a workspace", () => {
    const s = state("A", [ws("A", "a1", ["a1", "a2"])], [tab("a1"), tab("a2")]);
    const next = reconcile(s, { ws: null, tabs: new Map([["A", "a2"]]) });
    expect(s.workspaces[0].active_tab_id).toBe("a2");
    expect(next.tabs.get("A")).toBe("a2");
  });

  it("clears the tab expectation once the poll confirms it", () => {
    const s = state("A", [ws("A", "a2", ["a1", "a2"])], [tab("a1"), tab("a2")]);
    const next = reconcile(s, { ws: null, tabs: new Map([["A", "a2"]]) });
    expect(s.workspaces[0].active_tab_id).toBe("a2");
    expect(next.tabs.has("A")).toBe(false);
  });

  it("drops a tab expectation if the tab is gone from the workspace", () => {
    const s = state("A", [ws("A", "a1", ["a1"])], [tab("a1")]);
    const next = reconcile(s, { ws: null, tabs: new Map([["A", "ghost"]]) });
    expect(s.workspaces[0].active_tab_id).toBe("a1");
    expect(next.tabs.has("A")).toBe(false);
  });
});
