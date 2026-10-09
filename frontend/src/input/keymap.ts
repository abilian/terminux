// Global keyboard shortcuts (functional spec §8). One of three input
// surfaces feeding the command bus in ``./commands.ts``; ``keymap``
// just maps physical chords to command ids.
//
// Modifier conventions (see ./platform.ts):
//   macOS  — Cmd        for app shortcuts; Ctrl flows to the shell.
//   Linux and Windows — Ctrl+Shift for app shortcuts (the GNOME Terminal
//            and Windows Terminal convention); raw Ctrl flows to the shell,
//            except the zoom keys, which those terminals also take bare.
//
// Key matching uses ``e.code`` (layout-independent: ``KeyT``/``Digit1``/
// ``BracketLeft``) rather than ``e.key`` for any chord that requires Shift
// on Linux — Shift mutates ``e.key`` (``"t"``→``"T"``, ``"1"``→``"!"``,
// ``"="``→``"+"``) and a single check needs to fire on both platforms.

import { invoke } from "./commands";
import { IS_MAC, IS_WINDOWS, appMod } from "./platform";

// Zoom keys: the typed character wins (``-`` sits on the 6 key on AZERTY,
// and the key in the US ``=`` position types ``-`` on the Mac French
// layout); the physical key (``e.code``) is the fallback for chords where
// Shift changed the character (``_``, ``)``) or the numpad.
function zoomCommand(e: KeyboardEvent): string | null {
  if (e.key === "+" || e.key === "=") {
    return "view.zoom.in";
  }
  if (e.key === "-") {
    return "view.zoom.out";
  }
  if (e.code === "Equal" || e.code === "NumpadAdd") {
    return "view.zoom.in";
  }
  if (e.code === "Minus" || e.code === "NumpadSubtract") {
    return "view.zoom.out";
  }
  if (e.code === "Digit0" || e.code === "Numpad0") {
    return "view.zoom.reset";
  }
  return null;
}

// Linux/Windows chords that live outside the ``appMod`` gate: F1 as a
// second key for the command palette, and bare Ctrl+= / Ctrl+- / Ctrl+0 for zoom, as in GNOME Terminal and
// Windows Terminal. Everything else — including workspace digit jumps —
// uses the unified Ctrl+Shift app modifier inside ``handleAppChord``.
function handleNonMacChord(e: KeyboardEvent): boolean {
  if (IS_MAC) {
    return false;
  }
  if (e.key === "F1" && !e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    return invoke("palette.command");
  }
  const zoom = zoomCommand(e);
  if (zoom && e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
    return invoke(zoom);
  }
  return false;
}

// Clipboard chords, Linux and Windows only (macOS has its native Edit
// menu): Ctrl+Shift+C / V / A, plus bare Ctrl+C and Ctrl+V on Windows as
// in Windows Terminal. Bare Ctrl+C copies only while something is
// selected (``edit.copy`` declines otherwise), so it still interrupts.
function clipboardCommand(e: KeyboardEvent): string | null {
  if (IS_MAC || !e.ctrlKey || e.altKey || e.metaKey) {
    return null;
  }
  if (e.shiftKey || IS_WINDOWS) {
    if (e.code === "KeyC") {
      return "edit.copy";
    }
    if (e.code === "KeyV") {
      return "edit.paste.keyboard";
    }
  }
  if (e.shiftKey && e.code === "KeyA") {
    return "edit.select-all";
  }
  return null;
}

function handleAppChord(e: KeyboardEvent): boolean {
  // Cmd/Ctrl+Shift+Alt+C — toggle iTerm2-style auto-copy on selection.
  if (e.altKey && e.code === "KeyC") {
    return invoke("view.copy-on-select.toggle");
  }

  const zoom = zoomCommand(e);
  if (zoom) {
    return invoke(zoom);
  }

  if (e.code === "KeyB") {
    return invoke("view.sidebar.toggle");
  }
  if (e.code === "KeyF") {
    return invoke("view.find");
  }

  // Command palette: Cmd+Shift+P on macOS, Ctrl+Shift+P elsewhere (the
  // VS Code / Windows Terminal chord). The quick switcher is Cmd+P on
  // macOS; Linux/Windows can't take bare Ctrl+P (shell history), so it
  // lives on Ctrl+Shift+O.
  if (e.code === "KeyP") {
    return invoke(IS_MAC && !e.shiftKey ? "palette.quick" : "palette.command");
  }
  if (!IS_MAC && e.code === "KeyO") {
    return invoke("palette.quick");
  }

  if (e.code === "KeyT") {
    return invoke("tab.new");
  }
  if (e.code === "KeyW") {
    return invoke("tab.close");
  }
  if (e.code === "KeyN") {
    return invoke("workspace.new");
  }

  if (e.code === "BracketLeft") {
    return invoke("tab.prev");
  }
  if (e.code === "BracketRight") {
    return invoke("tab.next");
  }
  if (e.code === "ArrowLeft" && e.shiftKey) {
    return invoke("tab.prev");
  }
  if (e.code === "ArrowRight" && e.shiftKey) {
    return invoke("tab.next");
  }
  if (e.code === "ArrowUp" && e.shiftKey) {
    return invoke("workspace.prev");
  }
  if (e.code === "ArrowDown" && e.shiftKey) {
    return invoke("workspace.next");
  }

  // Cmd+1..9 (macOS) / Ctrl+Shift+1..9 (Linux). ``e.code`` is
  // layout-independent — important on Linux where Shift+1 makes
  // ``e.key`` equal "!" but the code stays "Digit1".
  const m = /^Digit([1-9])$/.exec(e.code);
  if (m) {
    return invoke(`workspace.jump.${m[1]}`);
  }

  return false;
}

export function installShortcuts(): void {
  // Capture phase: the focused xterm otherwise consumes the keydown before
  // it bubbles to window, so app chords never fire.
  window.addEventListener(
    "keydown",
    (e: KeyboardEvent) => {
      const clip = clipboardCommand(e);
      if (clip === "edit.paste.keyboard") {
        // Keep the default action, the webview's own paste; only xterm
        // must not see the key (it would send ^V).
        e.stopPropagation();
        invoke(clip);
        return;
      }
      // Ctrl+Shift+C with nothing selected does nothing; only Windows'
      // bare Ctrl+C falls through to the shell.
      let handled = clip ? invoke(clip) || e.shiftKey : handleNonMacChord(e);
      if (!handled && !clip && appMod(e)) {
        handled = handleAppChord(e);
      }
      if (handled) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true,
  );
}
