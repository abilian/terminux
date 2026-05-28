// Tab bar: tabs for the active workspace, inline rename, close, and nav.

import { api } from "./api";
import { makeRenameInput } from "./rename";
import { makeDraggable, recentlyReordered } from "./reorder";
import {
  activeWorkspace,
  getState,
  refresh,
  setActiveTabOptimistic,
} from "./store";
import { disposeSession } from "./terminal";

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

export function renderTabs(): void {
  // Inline-rename guard: same shape as renderSidebar — a poll-driven
  // re-render would otherwise destroy the in-progress <input> and
  // reseed it from the polled title, wiping the user's typing.
  if (editingTabId !== null) return;
  const state = getState();
  const bar = document.getElementById("tabbar");
  if (!state || !bar) return;
  bar.innerHTML = "";
  const ws = activeWorkspace();
  if (!ws) return;
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
