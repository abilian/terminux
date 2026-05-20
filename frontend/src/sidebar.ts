// Workspaces sidebar: list rows, inline rename, close, and prev/next nav.

import { api } from "./api";
import { makeRenameInput } from "./rename";
import { makeDraggable, recentlyReordered } from "./reorder";
import { getState, refresh } from "./store";
import { disposeSession } from "./terminal";

let editingWsId: string | null = null;

export function renderSidebar(): void {
  const state = getState();
  const list = document.getElementById("ws-list");
  if (!state || !list) return;
  list.innerHTML = "";
  state.workspaces.forEach((w, idx) => {
    const row = document.createElement("div");
    row.className =
      "ws-row" + (w.id === state.active_workspace_id ? " active" : "");

    // Slot 1-9 surfaces the Cmd/Ctrl+<N> shortcut; later slots get a blank
    // spacer so the names still line up.
    const slot = document.createElement("span");
    slot.className = "slot";
    if (idx < 9) {
      slot.classList.add("keycap");
      slot.textContent = String(idx + 1);
    }
    row.appendChild(slot);

    const dot = document.createElement("span");
    if (w.attention && w.id !== state.active_workspace_id) {
      dot.className = "attn";
      dot.title = "A tab wants attention";
      dot.textContent = "🔔";
    } else {
      dot.className = "dot " + w.status;
    }
    row.appendChild(dot);

    const beginRename = (e?: Event): void => {
      e?.stopPropagation();
      editingWsId = w.id;
      renderSidebar();
    };

    if (editingWsId === w.id) {
      row.appendChild(
        makeRenameInput(
          w.name,
          "name-input",
          (name) => {
            editingWsId = null;
            api(`/workspaces/${w.id}`, {
              method: "PATCH",
              body: JSON.stringify({ name }),
            }).then(refresh);
          },
          () => {
            editingWsId = null;
            renderSidebar();
          },
        ),
      );
    } else {
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = w.name;
      name.ondblclick = beginRename;
      row.appendChild(name);

      const edit = document.createElement("span");
      edit.className = "edit";
      edit.title = "Rename";
      edit.textContent = "✎";
      edit.onclick = beginRename;
      row.appendChild(edit);

      const close = document.createElement("span");
      close.className = "x";
      close.title = "Close";
      close.textContent = "✕";
      close.onclick = (e: MouseEvent): void => {
        e.stopPropagation();
        api(`/workspaces/${w.id}`, { method: "DELETE" }).then(refresh);
      };
      row.appendChild(close);
    }
    row.onclick = (): void => {
      if (recentlyReordered()) return; // ignore the click after a drag
      api(`/workspaces/${w.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: true }),
      }).then(refresh);
    };
    if (editingWsId !== w.id) {
      makeDraggable(
        row,
        w.id,
        () => getState()?.workspaces.map((x) => x.id) ?? [],
        (order) => {
          api(`/workspaces/${w.id}`, {
            method: "PATCH",
            body: JSON.stringify({ order }),
          }).then(refresh);
        },
      );
    }
    list.appendChild(row);
  });
}

// cmux parity: closing the last tab closes the workspace; the backend then
// activates a sibling (or creates a fresh one). The app never quits.
export function closeWorkspace(wsId: string): void {
  const state = getState();
  const w = state?.workspaces.find((x) => x.id === wsId);
  for (const tid of w?.tab_ids ?? []) disposeSession(tid);
  api(`/workspaces/${wsId}`, { method: "DELETE" }).then(refresh);
}

export function switchWorkspace(delta: number): void {
  const state = getState();
  if (!state || state.workspaces.length < 2) return;
  const n = state.workspaces.length;
  let i = state.workspaces.findIndex((w) => w.id === state.active_workspace_id);
  if (i < 0) i = 0;
  const next = state.workspaces[(i + delta + n) % n];
  api(`/workspaces/${next.id}`, {
    method: "PATCH",
    body: JSON.stringify({ active: true }),
  }).then(refresh);
}
