// The store's fetch/optimistic machinery: polls render without activating,
// optimistic switches repaint immediately and queue ordered PATCHes, and a
// stale poll cannot roll back the user's latest intent.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StateView } from "../src/state/types";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../src/state/api", () => ({
  api: mocks.api,
  TOKEN: "t",
  send: (method: string, path: string, body?: object) =>
    mocks.api(path, { method, body: body && JSON.stringify(body) }),
}));

type Store = typeof import("../src/state/store");

function serverState(activeWs: string): StateView {
  return {
    workspaces: [
      {
        id: "w1",
        name: "one",
        tab_ids: ["t1"],
        active_tab_id: "t1",
        status: activeWs === "w1" ? "active" : "idle",
        active_seconds: 0,
        last_used_at: null,
        ready_since: null,
      },
      {
        id: "w2",
        name: "two",
        tab_ids: ["t2"],
        active_tab_id: "t2",
        status: activeWs === "w2" ? "active" : "idle",
        active_seconds: 0,
        last_used_at: null,
        ready_since: null,
      },
    ],
    tabs: {},
    active_workspace_id: activeWs,
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

let store: Store;
let served: StateView;
let rendered: number;
let activated: number;

beforeEach(async () => {
  vi.resetModules();
  store = await import("../src/state/store");
  served = serverState("w1");
  rendered = 0;
  activated = 0;
  mocks.api.mockReset();
  mocks.api.mockImplementation((path: string) => {
    if (path === "/state") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(served) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
  store.configure({
    onRender: () => {
      rendered++;
    },
    onActivate: () => {
      activated++;
    },
  });
});

describe("store", () => {
  it("refresh renders and activates; poll only renders", async () => {
    await store.refresh();
    expect(store.getState()?.active_workspace_id).toBe("w1");
    expect([rendered, activated]).toEqual([1, 1]);
    await store.poll();
    expect([rendered, activated]).toEqual([2, 1]);
  });

  it("optimistic switch repaints locally, then PATCHes and re-polls", async () => {
    await store.refresh();
    await store.setActiveWorkspaceOptimistic("w2");
    // The local flip happened before any PATCH round-trip.
    expect(store.getState()?.active_workspace_id).toBe("w2");
    expect(store.activeWorkspace()?.id).toBe("w2");
    expect(activated).toBe(2);
    // Drain the activation queue: PATCH to w2, then a follow-up poll.
    await new Promise((r) => setTimeout(r, 0));
    const calls = mocks.api.mock.calls.map((c: unknown[]) => c[0]);
    expect(calls).toContain("/workspaces/w2");
    expect(calls.filter((p: unknown) => p === "/state").length).toBeGreaterThan(
      1,
    );
  });

  it("a stale poll cannot roll back the user's latest switch", async () => {
    await store.refresh();
    await store.setActiveWorkspaceOptimistic("w2");
    // The server still reports w1 (our PATCH hasn't landed yet).
    await store.poll();
    expect(store.getState()?.active_workspace_id).toBe("w2");
    // Once the server agrees, the expectation clears and w2 sticks.
    served = serverState("w2");
    await store.poll();
    expect(store.getState()?.active_workspace_id).toBe("w2");
  });

  it("optimistic tab switch updates the workspace's active tab", async () => {
    served.workspaces[0].tab_ids = ["t1", "t3"];
    await store.refresh();
    await store.setActiveTabOptimistic("w1", "t3");
    expect(store.activeWorkspace()?.active_tab_id).toBe("t3");
    // A stale poll (still reporting t1) does not roll it back.
    await store.poll();
    expect(store.activeWorkspace()?.active_tab_id).toBe("t3");
  });

  it("one optimistic switch moves to another workspace's tab", async () => {
    served.workspaces[1].tab_ids = ["t2", "t4"];
    await store.refresh();
    await store.activateOptimistic("w2", "t4");
    expect(store.activeWorkspace()?.id).toBe("w2");
    expect(store.activeWorkspace()?.active_tab_id).toBe("t4");
    expect(activated).toBe(2); // one local repaint, not one per id
    await new Promise((r) => setTimeout(r, 0));
    const patches = mocks.api.mock.calls.filter(
      (c: unknown[]) => c[0] === "/workspaces/w2",
    );
    expect(patches).toHaveLength(1);
    expect(JSON.parse((patches[0][1] as { body: string }).body)).toEqual({
      active: true,
      active_tab_id: "t4",
    });
  });

  it("a failed refresh or poll keeps the last state and doesn't reject", async () => {
    await store.refresh();
    mocks.api.mockImplementation(() =>
      Promise.resolve({ ok: false, status: 403 }),
    );
    await expect(store.refresh()).resolves.toBeUndefined();
    expect(store.getState()?.active_workspace_id).toBe("w1");
    expect([rendered, activated]).toEqual([1, 1]);
    await expect(store.poll()).resolves.toBeUndefined();
    expect(rendered).toBe(1); // nothing new to render
  });

  it("activeSession returns the live session of the active tab", async () => {
    await store.refresh();
    expect(store.activeSession()).toBeNull();
    const fake = { id: "fake" } as never;
    store.sessions.set("t1", fake);
    expect(store.activeSession()).toBe(fake);
    store.sessions.clear();
  });
});
