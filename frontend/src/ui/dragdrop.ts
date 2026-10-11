// Drag-and-drop. File drops are handled natively in Python (app.py):
// WKWebView hides real file paths from JS, so pywebview's Python drop handler
// is the only place the full path is available. Here we only (a) allow drops
// by preventing the webview's default navigate-to-file, and (b) handle dragged
// plain text (e.g. a selection from another app), which the native path skips.

import { activeSession } from "../state/store";
import { pasteText } from "../term/clipboard";

export function installDragAndDrop(): void {
  window.addEventListener("dragover", (e: DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = "copy";
    }
  });

  window.addEventListener("drop", (e: DragEvent) => {
    e.preventDefault(); // never navigate to the dropped file
    const dt = e.dataTransfer;
    if (!dt || dt.files.length) {
      return;
    } // files → native handler
    // As a paste: claims the terminal (another window may own it) and
    // brackets the text when the program asked for bracketed paste.
    pasteText(dt.getData("text/plain"));
    activeSession()?.term.focus();
  });
}
