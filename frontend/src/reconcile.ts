// Race guard for the optimistic switch helpers in store.ts.
//
// Two distinct races motivate this:
//
// 1. A ``GET /api/state`` poll started **before** our optimistic
//    PATCH arrives at the backend comes back with a stale snapshot
//    (active id = the *previous* workspace). Naively replacing
//    ``state`` with the polled value overwrites the optimistic
//    switch and the UI "jumps back".
// 2. Rapid PATCHes race for the backend's ``AppController.lock``;
//    the order they win the lock is not necessarily the order they
//    were sent (store.ts solves this separately by serializing
//    PATCHes through a promise queue).
//
// ``reconcile`` is the pure piece of (1): given a freshly-polled
// state and the user's current expectations (the active ids most
// recently asked for locally), mutate the polled state in place to
// honour those expectations, and return the expectations that
// should still be tracked. Once the poll comes back agreeing with
// an expectation, that entry is dropped — the backend has caught
// up and is safe to be authoritative again.

import type { StateView } from "./types";

export interface Expectations {
  ws: string | null;
  tabs: Map<string, string>;
}

export function reconcile(
  fetched: StateView,
  expected: Expectations,
): Expectations {
  let nextWs = expected.ws;
  if (nextWs !== null) {
    const stillExists = fetched.workspaces.some((w) => w.id === nextWs);
    if (!stillExists) {
      nextWs = null;
    } else if (fetched.active_workspace_id === nextWs) {
      nextWs = null;
    } else {
      fetched.active_workspace_id = nextWs;
    }
  }
  const nextTabs = new Map<string, string>();
  for (const [wsId, tid] of expected.tabs) {
    const w = fetched.workspaces.find((x) => x.id === wsId);
    if (!w) continue; // workspace gone — drop the expectation
    if (w.active_tab_id === tid) continue; // backend agrees — drop
    if (!w.tab_ids.includes(tid)) continue; // tab gone — drop
    w.active_tab_id = tid;
    nextTabs.set(wsId, tid);
  }
  return { ws: nextWs, tabs: nextTabs };
}
