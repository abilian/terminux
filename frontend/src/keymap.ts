// Global keyboard shortcuts (functional spec §8).
//
// Modifier conventions (see ./platform.ts):
//   macOS  — Cmd        for app shortcuts; Ctrl flows to the shell.
//   Linux  — Ctrl+Shift for app shortcuts; raw Ctrl flows to the shell.
//
// Key matching uses ``e.code`` (layout-independent: ``KeyT``/``Digit1``/
// ``BracketLeft``) rather than ``e.key`` for any chord that requires Shift
// on Linux — Shift mutates ``e.key`` (``"t"``→``"T"``, ``"1"``→``"!"``,
// ``"="``→``"+"``) and a single check needs to fire on both platforms.

import { api } from "./api";
import { openCmdPalette } from "./cmdpalette";
import { openFind } from "./find";
import { applyFontSize, getFontSize, resetFontSize } from "./font";
import { openPalette } from "./palette";
import { toggleSidebar } from "./layout";
import { IS_MAC, appMod } from "./platform";
import { closeWorkspace, switchWorkspace } from "./sidebar";
import { activeWorkspace, getState, refresh } from "./store";
import { closeTab, switchTab } from "./tabs";

function switchToWorkspaceAt(idx: number): boolean {
  const state = getState();
  if (!state) return false;
  const target = state.workspaces[idx];
  if (!target) return false;
  void api(`/workspaces/${target.id}`, {
    method: "PATCH",
    body: JSON.stringify({ active: true }),
  }).then(refresh);
  return true;
}

// Linux-only chords that live outside the ``appMod`` gate: F1 for the
// command palette (provisional, see notes/future-considerations.md).
// Everything else — including workspace digit jumps — uses the unified
// Ctrl+Shift app modifier inside ``handleAppChord``.
function handleLinuxOnlyChord(e: KeyboardEvent): boolean {
  if (IS_MAC) return false;
  if (e.key === "F1" && !e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    openCmdPalette();
    return true;
  }
  return false;
}

function handleAppChord(e: KeyboardEvent): boolean {
  const ws = activeWorkspace();
  const state = getState();

  // Cmd/Ctrl+Shift+Alt+C — toggle iTerm2-style auto-copy on selection.
  if (e.altKey && e.code === "KeyC") {
    const next = !state?.ui.copy_on_select;
    void api("/ui", {
      method: "PATCH",
      body: JSON.stringify({ copy_on_select: next }),
    }).then(refresh);
    return true;
  }

  // Font zoom uses ``e.code`` so Shift on Linux doesn't matter (``+``,
  // ``_``, ``)`` would otherwise hide ``=``, ``-``, ``0`` on shifted layouts).
  if (e.code === "Equal" || e.code === "NumpadAdd") {
    applyFontSize(getFontSize() + 1);
    return true;
  }
  if (e.code === "Minus" || e.code === "NumpadSubtract") {
    applyFontSize(getFontSize() - 1);
    return true;
  }
  if (e.code === "Digit0" || e.code === "Numpad0") {
    resetFontSize();
    return true;
  }

  if (e.code === "KeyB") {
    toggleSidebar();
    return true;
  }
  if (e.code === "KeyF") {
    openFind();
    return true;
  }

  // Cmd+Shift+P on macOS opens the command palette. On Linux the same
  // physical chord (Ctrl+Shift+P) *is* the appMod for P — i.e. the quick
  // switcher — so the secondary action lives on F1 instead, handled above.
  if (IS_MAC && e.shiftKey && e.code === "KeyP") {
    openCmdPalette();
    return true;
  }
  if (e.code === "KeyP") {
    openPalette();
    return true;
  }

  if (e.code === "KeyT" && ws) {
    void api(`/workspaces/${ws.id}/tabs`, { method: "POST" }).then(refresh);
    return true;
  }
  if (e.code === "KeyW") {
    if (ws) {
      if (ws.tab_ids.length > 1 && ws.active_tab_id) closeTab(ws.active_tab_id);
      else closeWorkspace(ws.id);
    }
    return true;
  }
  if (e.code === "KeyN") {
    void api("/workspaces", { method: "POST" }).then(refresh);
    return true;
  }

  if (e.code === "BracketLeft") {
    switchTab(-1);
    return true;
  }
  if (e.code === "BracketRight") {
    switchTab(1);
    return true;
  }
  if (e.code === "ArrowLeft" && e.shiftKey) {
    switchTab(-1);
    return true;
  }
  if (e.code === "ArrowRight" && e.shiftKey) {
    switchTab(1);
    return true;
  }
  if (e.code === "ArrowUp" && e.shiftKey) {
    switchWorkspace(-1);
    return true;
  }
  if (e.code === "ArrowDown" && e.shiftKey) {
    switchWorkspace(1);
    return true;
  }

  // Cmd+1..9 (macOS) / Ctrl+Shift+1..9 (Linux). ``e.code`` is
  // layout-independent — important on Linux where Shift+1 makes
  // ``e.key`` equal "!" but the code stays "Digit1".
  const m = /^Digit([1-9])$/.exec(e.code);
  if (m) return switchToWorkspaceAt(Number(m[1]) - 1);

  return false;
}

export function installShortcuts(): void {
  // Capture phase: the focused xterm otherwise consumes the keydown before
  // it bubbles to window, so app chords never fire.
  window.addEventListener(
    "keydown",
    (e: KeyboardEvent) => {
      let handled = handleLinuxOnlyChord(e);
      if (!handled && appMod(e)) handled = handleAppChord(e);
      if (handled) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true,
  );
}
