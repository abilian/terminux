// App state + live terminal sessions, with a tiny render/activate hook so UI
// modules stay decoupled from the fetch/refresh cycle (no import cycles).

import type { FitAddon } from "@xterm/addon-fit";
import type { SearchAddon } from "@xterm/addon-search";
import type { SerializeAddon } from "@xterm/addon-serialize";
import type { Terminal } from "@xterm/xterm";

import { api } from "./api";
import { reconcile } from "./reconcile";
import type { StateView, WorkspaceView } from "./types";

export interface Session {
  term: Terminal;
  fit: FitAddon;
  search: SearchAddon;
  serialize: SerializeAddon;
  ws: WebSocket;
  host: HTMLDivElement;
  exited: boolean;
  // Marked when PTY output arrives; the periodic save loop clears it after
  // persisting the buffer.
  dirty: boolean;
}

// One live xterm per tab, kept alive while hidden (dormant streaming).
export const sessions = new Map<string, Session>();

let state: StateView | null = null;

type Hook = () => void | Promise<void>;
let onRender: Hook = () => {};
let onActivate: Hook = () => {};

export function configure(hooks: { onRender: Hook; onActivate: Hook }): void {
  onRender = hooks.onRender;
  onActivate = hooks.onActivate;
}

export function getState(): StateView | null {
  return state;
}

export function activeWorkspace(): WorkspaceView | null {
  if (!state) return null;
  const id = state.active_workspace_id;
  return state.workspaces.find((w) => w.id === id) ?? null;
}

export function activeSession(): Session | null {
  const ws = activeWorkspace();
  if (!ws || !ws.active_tab_id) return null;
  return sessions.get(ws.active_tab_id) ?? null;
}

// Two distinct races motivated the machinery below:
//
// 1. A ``GET /api/state`` poll started **before** our optimistic
//    PATCH arrives at the backend comes back with a stale snapshot
//    (active id = the *previous* workspace). ``fetchState`` then
//    overwrites the optimistic state and the UI "jumps back".
// 2. Rapid PATCHes race for the backend's ``AppController.lock``;
//    the order they win the lock is not the order they were sent,
//    so the backend can settle on workspace B even though the
//    user's last intent was C.
//
// ``activationQueue`` serializes outgoing PATCHes so the backend
// sees them in the order the user issued them (fix for #2).
// ``expectedActiveWs`` / ``expectedActiveTabByWs`` carry the
// user's latest local intent; on each fetch, ``reconcile`` overrides
// the polled active ids with the expectation until a poll agrees
// — only then is the expectation cleared (fix for #1).
let activationQueue: Promise<unknown> = Promise.resolve();
let expectedActiveWs: string | null = null;
const expectedActiveTabByWs = new Map<string, string>();

function enqueueActivation(call: () => Promise<unknown>): void {
  activationQueue = activationQueue.then(call).catch(() => undefined);
}

async function fetchState(): Promise<void> {
  const r = await api("/state");
  const fetched = (await r.json()) as StateView;
  const next = reconcile(fetched, {
    ws: expectedActiveWs,
    tabs: expectedActiveTabByWs,
  });
  expectedActiveWs = next.ws;
  expectedActiveTabByWs.clear();
  for (const [k, v] of next.tabs) expectedActiveTabByWs.set(k, v);
  state = fetched;
}

// Full refresh: re-render and (re)activate the focused terminal.
export async function refresh(): Promise<void> {
  await fetchState();
  await onRender();
  await onActivate();
}

// Lightweight poll: re-render only, so it never steals terminal focus.
export async function poll(): Promise<void> {
  await fetchState();
  await onRender();
}

// Apply an already-mutated local state: re-render and re-activate without
// hitting the network. Used by the optimistic switch helpers so a click
// re-paints in one frame instead of waiting on PATCH + GET /state.
async function localApply(): Promise<void> {
  await onRender();
  await onActivate();
}

// Optimistic workspace switch. Mutates `state` to flip the active id and
// re-renders right away, then queues the PATCH so the backend sees
// switches in the order they were issued. The PATCH is followed by an
// immediate ``poll()`` so the local state catches up with whatever the
// backend changed on the way through (notably the dwell-gated
// has_unseen_output clearing) without waiting for the 2 s poll tick —
// kills the "bell briefly reappears" flicker without mirroring backend
// logic on the client. ``expectedActiveWs`` keeps the local truth
// intact across any stale polls already in flight.
//
// NOTE: ``has_unseen_output`` is *not* cleared optimistically — the
// backend defers that until you dwell long enough, and matching the
// backend's exact rule on the client would just duplicate logic that
// can drift. The follow-up ``poll()`` is the sync point instead.
export async function setActiveWorkspaceOptimistic(
  wsId: string,
): Promise<void> {
  if (!state || state.active_workspace_id === wsId) return;
  const w = state.workspaces.find((x) => x.id === wsId);
  if (!w) return;
  state.active_workspace_id = wsId;
  w.status = "active";
  for (const other of state.workspaces) {
    if (other.id !== wsId && other.status === "active") {
      // Best-guess fallback; the follow-up poll will promote it back
      // to unseen / busy / exited / idle as the backend computes it.
      other.status = "idle";
    }
  }
  expectedActiveWs = wsId;
  await localApply();
  enqueueActivation(async () => {
    await api(`/workspaces/${wsId}`, {
      method: "PATCH",
      body: JSON.stringify({ active: true }),
    });
    await poll();
  });
}

// Optimistic tab switch within a workspace. Same shape as the workspace
// helper above — local active-id flip, render, queued PATCH, expectation,
// follow-up poll.
export async function setActiveTabOptimistic(
  wsId: string,
  tid: string,
): Promise<void> {
  if (!state) return;
  const w = state.workspaces.find((x) => x.id === wsId);
  if (!w || w.active_tab_id === tid) return;
  w.active_tab_id = tid;
  expectedActiveTabByWs.set(wsId, tid);
  await localApply();
  enqueueActivation(async () => {
    await api(`/workspaces/${wsId}`, {
      method: "PATCH",
      body: JSON.stringify({ active_tab_id: tid }),
    });
    await poll();
  });
}
