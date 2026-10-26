// App state + live terminal sessions, with a tiny render/activate hook so UI
// modules stay decoupled from the fetch/refresh cycle (no import cycles).

import type { FitAddon } from "@xterm/addon-fit";
import type { SearchAddon } from "@xterm/addon-search";
import type { SerializeAddon } from "@xterm/addon-serialize";
import type { Terminal } from "@xterm/xterm";

import { api, send } from "./api";
import type { Kitty } from "../term/kitty";
import { reconcile } from "./reconcile";
import type { StateView, WorkspaceView } from "./types";

export interface Session {
  term: Terminal;
  fit: FitAddon;
  search: SearchAddon;
  serialize: SerializeAddon;
  // Live PTY socket; null while (re)connecting. Reassigned on every
  // reconnect — always read the current value, never capture it.
  ws: WebSocket | null;
  host: HTMLDivElement;
  exited: boolean;
  // Set by disposeSession — tells an in-flight reconnect loop to stop.
  disposed: boolean;
  // True while the reconnect loop owns this session's connection.
  reconnecting: boolean;
  // Stateful kitty-protocol codec: scans output to learn the app's keyboard
  // mode, encodes Enter accordingly. One per session — the learned state
  // must survive websocket reconnects.
  kitty: Kitty;
  // Marked when PTY output arrives; the periodic save loop clears it after
  // persisting the buffer.
  dirty: boolean;
  // Whether this client currently owns the terminal on the server: its size
  // is the PTY's and only its input is applied. Reset per connection.
  owner: boolean;
  // True from each (re)connect until the server's replayed backlog is
  // parsed: xterm answers the queries in it (cursor position, colors...),
  // and those stale answers must not reach the shell. Reset per connection.
  replaying: boolean;
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
  if (!state) {
    return null;
  }
  const id = state.active_workspace_id;
  return state.workspaces.find((w) => w.id === id) ?? null;
}

export function activeSession(): Session | null {
  const ws = activeWorkspace();
  if (!ws || !ws.active_tab_id) {
    return null;
  }
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
  // A failed switch must not jam the queue, but it must show up.
  activationQueue = activationQueue.then(call).catch((err: unknown) => {
    console.error("switch failed:", err);
  });
}

async function fetchState(): Promise<void> {
  const r = await api("/state");
  if (!r.ok) {
    throw new Error(`GET /api/state: HTTP ${r.status}`);
  }
  const fetched = (await r.json()) as StateView;
  const next = reconcile(fetched, {
    ws: expectedActiveWs,
    tabs: expectedActiveTabByWs,
  });
  expectedActiveWs = next.ws;
  expectedActiveTabByWs.clear();
  for (const [k, v] of next.tabs) {
    expectedActiveTabByWs.set(k, v);
  }
  state = fetched;
}

// Full refresh: re-render and (re)activate the focused terminal. Called
// after every user action (``.then(refresh)``); a failed fetch (backend
// stall, sleeping laptop) leaves the last state on screen, and the 2 s
// poll catches up once the backend answers again.
export async function refresh(): Promise<void> {
  try {
    await fetchState();
  } catch {
    return;
  }
  await onRender();
  await onActivate();
}

/** ``send`` a change, then refresh the screen. */
export async function mutate(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: object,
): Promise<void> {
  await send(method, path, body);
  await refresh();
}

// Lightweight poll: re-render only, so it never steals terminal focus.
// Like ``refresh``, a failed fetch keeps the last state; a render error
// propagates.
export async function poll(): Promise<void> {
  try {
    await fetchState();
  } catch {
    return;
  }
  await onRender();
}

// Apply an already-mutated local state: re-render and re-activate without
// hitting the network. Used by the optimistic switch helpers so a click
// re-paints in one frame instead of waiting on PATCH + GET /state.
async function localApply(): Promise<void> {
  await onRender();
  await onActivate();
}

// Optimistic switch to a workspace and, optionally, one of its tabs.
// Mutates `state` to flip the active ids and re-renders right away, then
// queues one PATCH so the backend sees switches in the order they were
// issued. The PATCH is followed by an immediate ``poll()`` so the local
// state catches up with whatever the backend changed on the way through
// (statuses, unseen flags) without waiting for the 2 s poll tick. The
// expectations keep the local truth intact across any stale polls
// already in flight.
export async function activateOptimistic(
  wsId: string,
  tid?: string,
): Promise<void> {
  const w = state?.workspaces.find((x) => x.id === wsId);
  if (!state || !w) {
    return;
  }
  const body: { active?: true; active_tab_id?: string } = {};
  if (state.active_workspace_id !== wsId) {
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
    body.active = true;
  }
  if (tid !== undefined && w.active_tab_id !== tid) {
    w.active_tab_id = tid;
    expectedActiveTabByWs.set(wsId, tid);
    body.active_tab_id = tid;
  }
  if (body.active === undefined && body.active_tab_id === undefined) {
    return;
  }
  await localApply();
  enqueueActivation(async () => {
    await send("PATCH", `/workspaces/${wsId}`, body);
    await poll();
  });
}

export function setActiveWorkspaceOptimistic(wsId: string): Promise<void> {
  return activateOptimistic(wsId);
}

export function setActiveTabOptimistic(
  wsId: string,
  tid: string,
): Promise<void> {
  return activateOptimistic(wsId, tid);
}
