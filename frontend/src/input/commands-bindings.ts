// Wiring layer: maps command ids to the existing feature handlers,
// then exposes ``window.terminux.invoke`` so the native menu (Python
// side) can dispatch via ``evaluate_js``. Kept in a separate file
// from ``commands.ts`` so the pure registry stays import-light and
// node-testable.

import { invoke, register } from "./commands";
import { openCmdPalette } from "../ui/cmdpalette";
import { openFind } from "../ui/find";
import { applyFontSize, getFontSize, resetFontSize } from "../term/font";
import { toggleSidebar } from "../ui/layout";
import { openPalette } from "../ui/palette";
import { closeWorkspace, switchWorkspace } from "../ui/sidebar";
import { openConnectInfo } from "../ui/connectinfo";
import {
  copySelection,
  expectNativePaste,
  pasteFromClipboard,
  pasteText,
  selectAll,
} from "../term/clipboard";
import { openStatsPanel } from "../ui/statspanel";
import {
  activeWorkspace,
  getState,
  mutate,
  setActiveWorkspaceOptimistic,
} from "../state/store";
import { closeTab, renderTabs, switchTab } from "../ui/tabs";
import { byRecentActivity, byTimeSpent } from "../state/sorting";
import type { WorkspaceView } from "../state/types";

// In full screen, Chromium's Keyboard Lock hands the page the chords the
// browser otherwise keeps (Cmd/Ctrl+W, T, N...); holding Esc still exits.
// Other browsers just go full screen.
function toggleFullscreen(): void {
  if (document.fullscreenElement) {
    void document.exitFullscreen();
    return;
  }
  void document.documentElement
    .requestFullscreen()
    .then(() => navigator.keyboard?.lock());
}

function applySort(sort: (ws: WorkspaceView[]) => WorkspaceView[]): void {
  const state = getState();
  if (!state || state.workspaces.length < 2) {
    return;
  }
  const order = sort(state.workspaces).map((w) => w.id);
  void mutate("PATCH", `/workspaces/${order[0]}`, { order });
}

declare global {
  // Keyboard Lock, Chromium only (not in TypeScript's DOM types).
  interface Navigator {
    keyboard?: { lock(): Promise<void> };
  }
  interface Window {
    terminux: {
      invoke(id: string): boolean;
      pasteText(text: string): void;
    };
  }
}

export function installCommands(): void {
  // ----- workspaces ---------------------------------------------------
  register("workspace.new", () => {
    void mutate("POST", "/workspaces");
  });
  register("workspace.next", () => switchWorkspace(1));
  register("workspace.prev", () => switchWorkspace(-1));
  register("workspace.close", () => {
    const ws = activeWorkspace();
    if (ws) {
      closeWorkspace(ws.id);
    }
  });
  for (let i = 1; i <= 9; i++) {
    register(`workspace.jump.${i}`, () => {
      const state = getState();
      const target = state?.workspaces[i - 1];
      if (target) {
        void setActiveWorkspaceOptimistic(target.id);
      }
    });
  }

  // ----- tabs ---------------------------------------------------------
  register("tab.new", () => {
    const ws = activeWorkspace();
    if (ws) {
      void mutate("POST", `/workspaces/${ws.id}/tabs`);
    }
  });
  register("tab.close", () => {
    // Cmd+W parity: close the active tab; the last tab closes the
    // whole workspace.
    const ws = activeWorkspace();
    if (!ws) {
      return;
    }
    if (ws.tab_ids.length > 1 && ws.active_tab_id) {
      closeTab(ws.active_tab_id);
    } else {
      closeWorkspace(ws.id);
    }
  });
  register("tab.next", () => switchTab(1));
  register("tab.prev", () => switchTab(-1));

  // ----- overlays -----------------------------------------------------
  register("palette.quick", openPalette);
  register("palette.command", openCmdPalette);
  register("view.find", openFind);
  register("view.sidebar.toggle", () => {
    toggleSidebar();
    renderTabs(); // the workspace chip appears/disappears with the sidebar
  });

  // ----- font zoom ----------------------------------------------------
  register("view.zoom.in", () => applyFontSize(getFontSize() + 1));
  register("view.zoom.out", () => applyFontSize(getFontSize() - 1));
  register("view.zoom.reset", resetFontSize);

  // ----- clipboard (Windows/Linux; macOS uses its native Edit menu) -----
  register("edit.copy", copySelection);
  register("edit.paste", pasteFromClipboard);
  register("edit.paste.keyboard", expectNativePaste);
  register("edit.select-all", selectAll);

  // ----- prefs toggles -------------------------------------------------
  register("view.copy-on-select.toggle", () => {
    const next = !getState()?.ui.copy_on_select;
    void mutate("PATCH", "/ui", { copy_on_select: next });
  });
  register("view.scrollback-persist.toggle", () => {
    const next = !getState()?.ui.scrollback_persist;
    void mutate("PATCH", "/ui", { scrollback_persist: next });
  });

  // ----- session activity ---------------------------------------------
  register("view.fullscreen.toggle", toggleFullscreen);
  register("view.stats", () => openStatsPanel());
  register("view.connect-info", () => openConnectInfo());
  register("view.activity.reset", () => {
    void mutate("POST", "/activity/reset");
  });
  register("workspace.sort.time-spent", () => applySort(byTimeSpent));
  register("workspace.sort.recent", () => applySort(byRecentActivity));

  // Native menu reaches in here via pywebview's ``evaluate_js``.
  // pasteText: Windows' Edit → Paste reads the clipboard in Python (the
  // webview refuses the clipboard API) and hands the text over.
  window.terminux = { invoke, pasteText };
}
