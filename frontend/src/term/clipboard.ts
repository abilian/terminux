// Copy and paste for the active terminal. macOS needs none of this:
// pywebview gives the window a native Edit menu there. On Windows and
// Linux the webview has neither an Edit menu nor a context menu, so the
// keymap and the native menu dispatch here.

import { activeSession } from "../state/store";
import { claim } from "./terminal";

// How long a paste chord waits for the webview's own paste before
// falling back to reading the clipboard.
const NATIVE_PASTE_WAIT_MS = 100;

/** Copy the active terminal's selection; false when nothing is selected. */
export function copySelection(): boolean {
  const term = activeSession()?.term;
  const text = term?.getSelection();
  if (!term || !text) {
    return false;
  }
  if (navigator.clipboard) {
    void navigator.clipboard.writeText(text);
  } else {
    // No clipboard API outside a secure context (a remote http://
    // server): xterm's own copy handler fills the clipboard instead.
    document.execCommand("copy");
  }
  // Windows' Ctrl+C copies only while something is selected; clearing
  // the selection gives the next Ctrl+C back to the shell.
  term.clearSelection();
  return true;
}

export function selectAll(): void {
  activeSession()?.term.selectAll();
}

/** Paste ``text`` into the active terminal, as if typed by a paste. */
export function pasteText(text: string): void {
  const sess = activeSession();
  if (!sess || !text) {
    return;
  }
  claim(sess);
  sess.term.paste(text); // bracketed when the program asked for it
}

/**
 * Paste without a native paste event (the menu, or a chord the webview
 * doesn't bind). WebKitGTK honours ``execCommand("paste")`` because
 * pywebview enables JavaScript clipboard access there; elsewhere the
 * clipboard API reads the text, which may ask the user's permission.
 */
export function pasteFromClipboard(): void {
  const sess = activeSession();
  if (!sess) {
    return;
  }
  sess.term.focus();
  if (document.execCommand("paste")) {
    return; // a real paste event reached xterm
  }
  void navigator.clipboard?.readText().then(pasteText, () => {});
}

/**
 * A paste chord keeps its default action: the webview pastes into xterm's
 * textarea and xterm handles the ``paste`` event (bracketed paste
 * included), with no permission prompt. Where the webview binds nothing
 * to the chord (Ctrl+Shift+V on WebKitGTK), fall back after a moment.
 */
export function expectNativePaste(): void {
  let pasted = false;
  const onPaste = (): void => {
    pasted = true;
  };
  window.addEventListener("paste", onPaste, { capture: true, once: true });
  setTimeout(() => {
    window.removeEventListener("paste", onPaste, true);
    if (!pasted) {
      pasteFromClipboard();
    }
  }, NATIVE_PASTE_WAIT_MS);
}
