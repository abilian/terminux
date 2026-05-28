// Wiring layer: maps command ids to the existing feature handlers,
// then exposes ``window.terminux.invoke`` so the native menu (Python
// side) can dispatch via ``evaluate_js``. Kept in a separate file
// from ``commands.ts`` so the pure registry stays import-light and
// node-testable.

import { api } from "./api";
import { invoke, register } from "./commands";
import { openCmdPalette } from "./cmdpalette";
import { openFind } from "./find";
import { applyFontSize, getFontSize, resetFontSize } from "./font";
import { toggleSidebar } from "./layout";
import { openPalette } from "./palette";
import { closeWorkspace, switchWorkspace } from "./sidebar";
import { openStatsPanel } from "./statspanel";
import {
  activeWorkspace,
  getState,
  refresh,
  setActiveWorkspaceOptimistic,
} from "./store";
import { closeTab, switchTab } from "./tabs";

declare global {
  interface Window {
    terminux: { invoke(id: string): boolean };
  }
}

export function installCommands(): void {
  // ----- workspaces ---------------------------------------------------
  register("workspace.new", () => {
    void api("/workspaces", { method: "POST" }).then(refresh);
  });
  register("workspace.next", () => switchWorkspace(1));
  register("workspace.prev", () => switchWorkspace(-1));
  register("workspace.close", () => {
    const ws = activeWorkspace();
    if (ws) closeWorkspace(ws.id);
  });
  for (let i = 1; i <= 9; i++) {
    register(`workspace.jump.${i}`, () => {
      const state = getState();
      const target = state?.workspaces[i - 1];
      if (target) void setActiveWorkspaceOptimistic(target.id);
    });
  }

  // ----- tabs ---------------------------------------------------------
  register("tab.new", () => {
    const ws = activeWorkspace();
    if (ws) {
      void api(`/workspaces/${ws.id}/tabs`, { method: "POST" }).then(refresh);
    }
  });
  register("tab.close", () => {
    // Cmd+W parity: close the active tab; the last tab closes the
    // whole workspace.
    const ws = activeWorkspace();
    if (!ws) return;
    if (ws.tab_ids.length > 1 && ws.active_tab_id) closeTab(ws.active_tab_id);
    else closeWorkspace(ws.id);
  });
  register("tab.next", () => switchTab(1));
  register("tab.prev", () => switchTab(-1));

  // ----- overlays -----------------------------------------------------
  register("palette.quick", openPalette);
  register("palette.command", openCmdPalette);
  register("view.find", openFind);
  register("view.sidebar.toggle", toggleSidebar);

  // ----- font zoom ----------------------------------------------------
  register("view.zoom.in", () => applyFontSize(getFontSize() + 1));
  register("view.zoom.out", () => applyFontSize(getFontSize() - 1));
  register("view.zoom.reset", resetFontSize);

  // ----- prefs toggles -------------------------------------------------
  register("view.copy-on-select.toggle", () => {
    const next = !getState()?.ui.copy_on_select;
    void api("/ui", {
      method: "PATCH",
      body: JSON.stringify({ copy_on_select: next }),
    }).then(refresh);
  });
  register("view.scrollback-persist.toggle", () => {
    const next = !getState()?.ui.scrollback_persist;
    void api("/ui", {
      method: "PATCH",
      body: JSON.stringify({ scrollback_persist: next }),
    }).then(refresh);
  });

  // ----- session activity ---------------------------------------------
  register("view.stats", () => openStatsPanel());
  register("view.activity.reset", () => {
    void api("/activity/reset", { method: "POST" }).then(refresh);
  });
  register("workspace.reorder-by-activity", () => {
    const state = getState();
    if (!state || state.workspaces.length < 2) return;
    const order = [...state.workspaces]
      .sort((a, b) => b.active_seconds - a.active_seconds)
      .map((w) => w.id);
    const target = order[0];
    if (!target) return;
    void api(`/workspaces/${target}`, {
      method: "PATCH",
      body: JSON.stringify({ order }),
    }).then(refresh);
  });

  // Native menu reaches in here via pywebview's ``evaluate_js``.
  window.terminux = { invoke };
}
