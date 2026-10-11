// Workspaces sidebar as a Preact island: rows, inline rename, close, and
// prev/next nav. `renderSidebar` re-renders (diffs) the island on every
// poll; an in-progress rename or a mid-flight drag survives because the
// DOM is patched, never rebuilt.

import { render } from "preact";
import { useState } from "preact/hooks";

import { api } from "../state/api";
import { formatDuration } from "../util/duration";
import { RenameInput } from "./rename";
import { makeDraggable, recentlyReordered } from "./reorder";
import {
  getState,
  refresh,
  setActiveWorkspaceOptimistic,
} from "../state/store";
import { disposeSession } from "../term/terminal";
import type { WorkspaceView } from "../state/types";

const DOT_TOOLTIP: Record<string, string> = {
  active: "This workspace is the one in view",
  unseen: "Ready for review (a task finished or signalled here)",
  busy: "A foreground task is running",
  idle: "Nothing of note",
  exited: "All shells in this workspace have exited",
};

export function renderSidebar(): void {
  const list = document.getElementById("ws-list");
  if (list) {
    render(<WorkspaceList />, list);
  }
}

function WorkspaceList() {
  const [editing, setEditing] = useState<string | null>(null);
  const state = getState();
  if (!state) {
    return null;
  }
  return (
    <>
      {state.workspaces.map((w, idx) => (
        <WorkspaceRow
          key={w.id}
          w={w}
          idx={idx}
          active={w.id === state.active_workspace_id}
          editing={editing === w.id}
          setEditing={setEditing}
        />
      ))}
    </>
  );
}

interface RowProps {
  w: WorkspaceView;
  idx: number;
  active: boolean;
  editing: boolean;
  setEditing: (id: string | null) => void;
}

function WorkspaceRow({ w, idx, active, editing, setEditing }: RowProps) {
  const timeTitle = `Active time: ${formatDuration(w.active_seconds)}`;
  const beginRename = (e: Event): void => {
    e.stopPropagation();
    setEditing(w.id);
  };
  return (
    <div
      class={"ws-row" + (active ? " active" : "")}
      ref={(el) => {
        // Attach the mouse-event drag handler once per DOM node; the ref
        // callback re-fires on every diff and dataset.reorderId (set by
        // makeDraggable) marks nodes already wired.
        if (el && !el.dataset.reorderId) {
          makeDraggable(
            el,
            w.id,
            () => getState()?.workspaces.map((x) => x.id) ?? [],
            (order) => {
              void api(`/workspaces/${w.id}`, {
                method: "PATCH",
                body: JSON.stringify({ order }),
              }).then(refresh);
            },
          );
        }
      }}
      onClick={() => {
        if (recentlyReordered()) {
          return;
        } // ignore the click after a drag
        void setActiveWorkspaceOptimistic(w.id);
      }}
    >
      {/* Slot 1-9 surfaces the Cmd/Ctrl+<N> shortcut; later slots get a
          blank spacer so the names still line up. */}
      <span class={idx < 9 ? "slot keycap" : "slot"}>
        {idx < 9 ? String(idx + 1) : ""}
      </span>
      <span class={"dot " + w.status} title={DOT_TOOLTIP[w.status] ?? ""} />
      {editing ? (
        <RenameInput
          value={w.name}
          onCommit={(name) => {
            setEditing(null);
            void api(`/workspaces/${w.id}`, {
              method: "PATCH",
              body: JSON.stringify({ name }),
            }).then(refresh);
          }}
          onCancel={() => setEditing(null)}
        />
      ) : (
        <>
          <span class="name" title={timeTitle} onDblClick={beginRename}>
            {w.name}
          </span>
          {/* Inline at-a-glance active time. Suppressed at 0 so fresh
              workspaces don't carry a "0s" tag. */}
          {w.active_seconds > 0 && (
            <span class="active-time" title={timeTitle}>
              {formatDuration(w.active_seconds)}
            </span>
          )}
          <span class="edit" title="Rename" onClick={beginRename}>
            ✎
          </span>
          <span
            class="x"
            title="Close"
            onClick={(e) => {
              e.stopPropagation();
              closeWorkspace(w.id);
            }}
          >
            ✕
          </span>
        </>
      )}
    </div>
  );
}

// Closing the last tab closes the workspace; the backend then
// activates a sibling (or creates a fresh one). The app never quits.
export function closeWorkspace(wsId: string): void {
  const state = getState();
  const w = state?.workspaces.find((x) => x.id === wsId);
  for (const tid of w?.tab_ids ?? []) {
    disposeSession(tid);
  }
  api(`/workspaces/${wsId}`, { method: "DELETE" }).then(refresh);
}

export function switchWorkspace(delta: number): void {
  const state = getState();
  if (!state || state.workspaces.length < 2) {
    return;
  }
  const n = state.workspaces.length;
  let i = state.workspaces.findIndex((w) => w.id === state.active_workspace_id);
  if (i < 0) {
    i = 0;
  }
  const next = state.workspaces[(i + delta + n) % n];
  void setActiveWorkspaceOptimistic(next.id);
}
