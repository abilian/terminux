// Global keyboard shortcuts (functional spec §8).

import { api } from "./api";
import { openFind } from "./find";
import { applyFontSize, getFontSize, resetFontSize } from "./font";
import { openPalette } from "./palette";
import { toggleSidebar } from "./layout";
import { closeWorkspace, switchWorkspace } from "./sidebar";
import { activeWorkspace, getState, refresh } from "./store";
import { closeTab, switchTab } from "./tabs";

export function installShortcuts(): void {
  // Capture phase: the focused xterm otherwise consumes the keydown before
  // it bubbles to window, so app chords (Cmd/Ctrl+P/F/B/…) never fired.
  window.addEventListener(
    "keydown",
    (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      const ws = activeWorkspace();
      const state = getState();
      if (e.key === "=" || e.key === "+") {
        e.preventDefault();
        applyFontSize(getFontSize() + 1);
      } else if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        applyFontSize(getFontSize() - 1);
      } else if (e.key === "0") {
        e.preventDefault();
        resetFontSize();
      } else if (e.key === "b" || e.key === "B") {
        e.preventDefault(); // Cmd/Ctrl+B — toggle the workspaces sidebar
        toggleSidebar();
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault(); // Cmd/Ctrl+F — find in terminal
        openFind();
      } else if (e.key === "p" || e.key === "P") {
        e.preventDefault(); // Cmd/Ctrl+P — quick switch (also blocks print)
        openPalette();
      } else if (e.key === "t" && ws) {
        e.preventDefault();
        api(`/workspaces/${ws.id}/tabs`, { method: "POST" }).then(refresh);
      } else if (e.key === "w") {
        // Always preventDefault so the OS never closes the window / quits.
        e.preventDefault();
        if (ws) {
          if (ws.tab_ids.length > 1 && ws.active_tab_id)
            closeTab(ws.active_tab_id);
          else closeWorkspace(ws.id);
        }
      } else if (e.key === "n" || e.key === "N") {
        // cmux parity: Cmd/Ctrl+N creates a workspace (Shift optional).
        e.preventDefault();
        api("/workspaces", { method: "POST" }).then(refresh);
      } else if (e.code === "BracketLeft") {
        e.preventDefault(); // Cmd/Ctrl+Shift+[ — previous tab
        switchTab(-1);
      } else if (e.code === "BracketRight") {
        e.preventDefault(); // Cmd/Ctrl+Shift+] — next tab
        switchTab(1);
      } else if (e.shiftKey && e.key === "ArrowLeft") {
        e.preventDefault(); // Shift+Cmd+← — previous tab
        switchTab(-1);
      } else if (e.shiftKey && e.key === "ArrowRight") {
        e.preventDefault(); // Shift+Cmd+→ — next tab
        switchTab(1);
      } else if (e.shiftKey && e.key === "ArrowUp") {
        e.preventDefault(); // Shift+Cmd+↑ — previous workspace
        switchWorkspace(-1);
      } else if (e.shiftKey && e.key === "ArrowDown") {
        e.preventDefault(); // Shift+Cmd+↓ — next workspace
        switchWorkspace(1);
      } else if (/^[1-9]$/.test(e.key) && state) {
        const target = state.workspaces[Number(e.key) - 1];
        if (target) {
          e.preventDefault();
          api(`/workspaces/${target.id}`, {
            method: "PATCH",
            body: JSON.stringify({ active: true }),
          }).then(refresh);
        }
      }
      // If we acted on the chord, keep it from also reaching the terminal.
      if (e.defaultPrevented) e.stopPropagation();
    },
    true,
  );
}
