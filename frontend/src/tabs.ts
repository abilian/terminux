// Tab bar: tabs for the active workspace, inline rename, close, and nav.

import { api } from "./api";
import { toggleSidebar } from "./layout";
import { makeRenameInput } from "./rename";
import { makeDraggable, recentlyReordered } from "./reorder";
import {
  activeWorkspace,
  getState,
  refresh,
  setActiveTabOptimistic,
} from "./store";
import { disposeSession } from "./terminal";
import type { StateView, WorkspaceView } from "./types";

let editingTabId: string | null = null;

export function closeTab(tid: string): void {
  disposeSession(tid);
  api(`/tabs/${tid}`, { method: "DELETE" }).then(refresh);
}

export function switchTab(delta: number): void {
  const ws = activeWorkspace();
  if (!ws || ws.tab_ids.length < 2 || !ws.active_tab_id) return;
  const len = ws.tab_ids.length;
  const i = ws.tab_ids.indexOf(ws.active_tab_id);
  const next = ws.tab_ids[(i + delta + len) % len];
  void setActiveTabOptimistic(ws.id, next);
}

export function isEditingTab(): boolean {
  return editingTabId !== null;
}

function sidebarHidden(): boolean {
  return document.getElementById("sidebar")?.style.display === "none";
}

function makeWsChip(state: StateView, ws: WorkspaceView): HTMLDivElement {
  const chip = document.createElement("div");
  chip.id = "ws-chip";
  const n = ws.tab_ids.length;
  chip.title = `${ws.name} (${n} tab${n === 1 ? "" : "s"}) — click to show the sidebar`;
  const dot = document.createElement("span");
  dot.className = "dot " + ws.status;
  chip.appendChild(dot);
  // Same keycap the sidebar shows: ties the chip to Cmd/Ctrl+1..9.
  const idx = state.workspaces.findIndex((w) => w.id === ws.id);
  if (idx >= 0 && idx < 9) {
    const slot = document.createElement("span");
    slot.className = "keycap";
    slot.textContent = String(idx + 1);
    chip.appendChild(slot);
  }
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = ws.name;
  chip.appendChild(name);
  const sep = document.createElement("span");
  sep.className = "sep";
  sep.textContent = "❯";
  chip.appendChild(sep);
  chip.onclick = (): void => {
    toggleSidebar();
    renderTabs(); // the chip just made itself redundant
  };
  return chip;
}

export function renderTabs(): void {
  // Same shape as renderSidebar: the "skip while editing" guard lives
  // at the ``onRender`` call site so the dblclick-to-rename transition
  // can still mount its <input>.
  const state = getState();
  const bar = document.getElementById("tabbar");
  if (!state || !bar) return;
  bar.innerHTML = "";
  const ws = activeWorkspace();
  if (!ws) return;
  // With the sidebar hidden, nothing else on screen says which workspace
  // this is — the chip stands in for it (and clicking it brings the
  // sidebar back). Redundant, and therefore absent, while the sidebar is
  // visible.
  if (sidebarHidden()) bar.appendChild(makeWsChip(state, ws));
  // Tabs go in an overflow-clipped wrapper so the "+" sibling at the end
  // of #tabbar stays visible no matter how many tabs accrue.
  const list = document.createElement("div");
  list.id = "tabs-list";
  for (const tid of ws.tab_ids) {
    const t = state.tabs[tid];
    if (!t) continue;
    const el = document.createElement("div");
    el.className = "tab" + (tid === ws.active_tab_id ? " active" : "");
    // Full title on hover — visible text is ellipsized by CSS once the
    // tab hits its max-width.
    el.title = t.title;
    if (t.has_unseen_output && tid !== ws.active_tab_id) {
      const a = document.createElement("span");
      a.className = "activity";
      el.appendChild(a);
    }
    if (editingTabId === tid) {
      el.appendChild(
        makeRenameInput(
          t.title,
          "name-input",
          (title) => {
            editingTabId = null;
            api(`/tabs/${tid}`, {
              method: "PATCH",
              body: JSON.stringify({ title }),
            }).then(refresh);
          },
          () => {
            editingTabId = null;
            renderTabs();
          },
        ),
      );
    } else {
      const title = document.createElement("span");
      title.className = "title";
      title.textContent = t.title + (t.live ? "" : " (exited)");
      title.ondblclick = (e: MouseEvent): void => {
        e.stopPropagation();
        editingTabId = tid;
        renderTabs();
      };
      el.appendChild(title);

      const close = document.createElement("span");
      close.className = "x";
      close.title = "Close";
      close.textContent = "✕";
      close.onclick = (e: MouseEvent): void => {
        e.stopPropagation();
        closeTab(tid);
      };
      el.appendChild(close);
    }
    el.onclick = (): void => {
      if (recentlyReordered()) return; // ignore the click after a drag
      if (tid === ws.active_tab_id) return; // already active; lets dblclick rename
      void setActiveTabOptimistic(ws.id, tid);
    };
    if (editingTabId !== tid) {
      makeDraggable(
        el,
        tid,
        () => activeWorkspace()?.tab_ids.slice() ?? [],
        (order) => {
          api(`/workspaces/${ws.id}`, {
            method: "PATCH",
            body: JSON.stringify({ tab_order: order }),
          }).then(refresh);
        },
      );
    }
    list.appendChild(el);
  }
  bar.appendChild(list);
  const add = document.createElement("div");
  add.id = "new-tab";
  add.textContent = "+";
  add.title = "New tab";
  add.onclick = (): void => {
    api(`/workspaces/${ws.id}/tabs`, { method: "POST" }).then(refresh);
  };
  bar.appendChild(add);
}
