// Global keyboard shortcuts (functional spec §8). One of three input
// surfaces feeding the command bus in ``./commands.ts``; ``keymap``
// just maps physical chords to command ids.
//
// Modifier conventions (see ./platform.ts):
//   macOS  — Cmd        for app shortcuts; Ctrl flows to the shell.
//   Linux  — Ctrl+Shift for app shortcuts; raw Ctrl flows to the shell.
//
// Key matching uses ``e.code`` (layout-independent: ``KeyT``/``Digit1``/
// ``BracketLeft``) rather than ``e.key`` for any chord that requires Shift
// on Linux — Shift mutates ``e.key`` (``"t"``→``"T"``, ``"1"``→``"!"``,
// ``"="``→``"+"``) and a single check needs to fire on both platforms.

import { invoke } from "./commands";
import { IS_MAC, appMod } from "./platform";

// Linux-only chords that live outside the ``appMod`` gate: F1 for the
// command palette (provisional, see notes/future-considerations.md).
// Everything else — including workspace digit jumps — uses the unified
// Ctrl+Shift app modifier inside ``handleAppChord``.
function handleLinuxOnlyChord(e: KeyboardEvent): boolean {
  if (IS_MAC) return false;
  if (e.key === "F1" && !e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    return invoke("palette.command");
  }
  return false;
}

function handleAppChord(e: KeyboardEvent): boolean {
  // Cmd/Ctrl+Shift+Alt+C — toggle iTerm2-style auto-copy on selection.
  if (e.altKey && e.code === "KeyC") return invoke("view.copy-on-select.toggle");

  // Font zoom uses ``e.code`` so Shift on Linux doesn't matter (``+``,
  // ``_``, ``)`` would otherwise hide ``=``, ``-``, ``0`` on shifted layouts).
  if (e.code === "Equal" || e.code === "NumpadAdd") return invoke("view.zoom.in");
  if (e.code === "Minus" || e.code === "NumpadSubtract") {
    return invoke("view.zoom.out");
  }
  if (e.code === "Digit0" || e.code === "Numpad0") return invoke("view.zoom.reset");

  if (e.code === "KeyB") return invoke("view.sidebar.toggle");
  if (e.code === "KeyF") return invoke("view.find");

  // Cmd+Shift+P on macOS opens the command palette. On Linux the same
  // physical chord (Ctrl+Shift+P) *is* the appMod for P — i.e. the quick
  // switcher — so the secondary action lives on F1 instead, handled above.
  if (IS_MAC && e.shiftKey && e.code === "KeyP") return invoke("palette.command");
  if (e.code === "KeyP") return invoke("palette.quick");

  if (e.code === "KeyT") return invoke("tab.new");
  if (e.code === "KeyW") return invoke("tab.close");
  if (e.code === "KeyN") return invoke("workspace.new");

  if (e.code === "BracketLeft") return invoke("tab.prev");
  if (e.code === "BracketRight") return invoke("tab.next");
  if (e.code === "ArrowLeft" && e.shiftKey) return invoke("tab.prev");
  if (e.code === "ArrowRight" && e.shiftKey) return invoke("tab.next");
  if (e.code === "ArrowUp" && e.shiftKey) return invoke("workspace.prev");
  if (e.code === "ArrowDown" && e.shiftKey) return invoke("workspace.next");

  // Cmd+1..9 (macOS) / Ctrl+Shift+1..9 (Linux). ``e.code`` is
  // layout-independent — important on Linux where Shift+1 makes
  // ``e.key`` equal "!" but the code stays "Digit1".
  const m = /^Digit([1-9])$/.exec(e.code);
  if (m) return invoke(`workspace.jump.${m[1]}`);

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
