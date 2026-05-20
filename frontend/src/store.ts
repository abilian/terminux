// App state + live terminal sessions, with a tiny render/activate hook so UI
// modules stay decoupled from the fetch/refresh cycle (no import cycles).

import type { FitAddon } from "@xterm/addon-fit";
import type { SearchAddon } from "@xterm/addon-search";
import type { SerializeAddon } from "@xterm/addon-serialize";
import type { Terminal } from "@xterm/xterm";

import { api } from "./api";
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

async function fetchState(): Promise<void> {
  const r = await api("/state");
  state = (await r.json()) as StateView;
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
