// Tab bar as a Preact island: the workspace chip (when the sidebar is
// hidden), tabs with inline rename/close, and the "+" button. Diffed on
// every poll, so renames and drags in progress keep their DOM.

import { render } from "preact";
import { useState } from "preact/hooks";

import { api } from "../state/api";
import { toggleSidebar } from "./layout";
import { RenameInput } from "./rename";
import { makeDraggable, recentlyReordered } from "./reorder";
import {
  activeWorkspace,
  getState,
  refresh,
  setActiveTabOptimistic,
} from "../state/store";
import { disposeSession } from "../term/terminal";
import type { StateView, TabView, WorkspaceView } from "../state/types";

export function closeTab(tid: string): void {
  disposeSession(tid);
  api(`/tabs/${tid}`, { method: "DELETE" }).then(refresh);
}

export function switchTab(delta: number): void {
  const ws = activeWorkspace();
  if (!ws || ws.tab_ids.length < 2 || !ws.active_tab_id) {
    return;
  }
  const len = ws.tab_ids.length;
  const i = ws.tab_ids.indexOf(ws.active_tab_id);
  const next = ws.tab_ids[(i + delta + len) % len];
  void setActiveTabOptimistic(ws.id, next);
}

export function renderTabs(): void {
  const bar = document.getElementById("tabbar");
  if (bar) {
    render(<TabBar />, bar);
  }
}

function sidebarHidden(): boolean {
  return document.getElementById("sidebar")?.style.display === "none";
}

function TabBar() {
  const [editing, setEditing] = useState<string | null>(null);
  const state = getState();
  const ws = state ? activeWorkspace() : null;
  if (!state || !ws) {
    return null;
  }
  return (
    <>
      {/* With the sidebar hidden, nothing else on screen says which
          workspace this is — the chip stands in for it. */}
      {sidebarHidden() && <WsChip state={state} ws={ws} />}
      <div id="tabs-list">
        {ws.tab_ids.map((tid) => {
          const t = state.tabs[tid];
          if (!t) {
            return null;
          }
          return (
            <TabItem
              key={tid}
              t={t}
              tid={tid}
              ws={ws}
              editing={editing === tid}
              setEditing={setEditing}
            />
          );
        })}
      </div>
      <div
        id="new-tab"
        title="New tab"
        onClick={() => {
          void api(`/workspaces/${ws.id}/tabs`, { method: "POST" }).then(
            refresh,
          );
        }}
      >
        +
      </div>
    </>
  );
}

function WsChip({ state, ws }: { state: StateView; ws: WorkspaceView }) {
  const n = ws.tab_ids.length;
  // Same keycap the sidebar shows: ties the chip to Cmd/Ctrl+1..9.
  const idx = state.workspaces.findIndex((w) => w.id === ws.id);
  return (
    <div
      id="ws-chip"
      title={`${ws.name} (${n} tab${n === 1 ? "" : "s"}) — click to show the sidebar`}
      onClick={() => {
        toggleSidebar();
        renderTabs(); // the chip just made itself redundant
      }}
    >
      <span class={"dot " + ws.status} />
      {idx >= 0 && idx < 9 && <span class="keycap">{String(idx + 1)}</span>}
      <span class="name">{ws.name}</span>
      <span class="sep">❯</span>
    </div>
  );
}

interface TabProps {
  t: TabView;
  tid: string;
  ws: WorkspaceView;
  editing: boolean;
  setEditing: (id: string | null) => void;
}

function TabItem({ t, tid, ws, editing, setEditing }: TabProps) {
  return (
    <div
      class={"tab" + (tid === ws.active_tab_id ? " active" : "")}
      // Full title on hover — visible text is ellipsized by CSS.
      title={t.title}
      ref={(el) => {
        if (el && !el.dataset.reorderId) {
          makeDraggable(
            el,
            tid,
            () => activeWorkspace()?.tab_ids.slice() ?? [],
            (order) => {
              void api(`/workspaces/${ws.id}`, {
                method: "PATCH",
                body: JSON.stringify({ tab_order: order }),
              }).then(refresh);
            },
          );
        }
      }}
      onClick={() => {
        if (recentlyReordered()) {
          return;
        } // ignore the click after a drag
        if (tid === ws.active_tab_id) {
          return;
        } // active; lets dblclick rename
        void setActiveTabOptimistic(ws.id, tid);
      }}
    >
      {t.has_unseen_output && tid !== ws.active_tab_id && (
        <span class="activity" />
      )}
      {editing ? (
        <RenameInput
          value={t.title}
          onCommit={(title) => {
            setEditing(null);
            void api(`/tabs/${tid}`, {
              method: "PATCH",
              body: JSON.stringify({ title }),
            }).then(refresh);
          }}
          onCancel={() => setEditing(null)}
        />
      ) : (
        <>
          <span
            class="title"
            onDblClick={(e) => {
              e.stopPropagation();
              setEditing(tid);
            }}
          >
            {t.title + (t.live ? "" : " (exited)")}
          </span>
          <span
            class="x"
            title="Close"
            onClick={(e) => {
              e.stopPropagation();
              closeTab(tid);
            }}
          >
            ✕
          </span>
        </>
      )}
    </div>
  );
}
