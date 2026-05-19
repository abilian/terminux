// Drag-and-drop. File drops are handled natively in Python (app.py):
// WKWebView hides real file paths from JS, so pywebview's Python drop handler
// is the only place the full path is available. Here we only (a) allow drops
// by preventing the webview's default navigate-to-file, and (b) handle dragged
// plain text (e.g. a selection from another app), which the native path skips.

import { activeSession } from "./store";

const enc = new TextEncoder();

export function installDragAndDrop(): void {
  window.addEventListener("dragover", (e: DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  });

  window.addEventListener("drop", (e: DragEvent) => {
    e.preventDefault(); // never navigate to the dropped file
    const dt = e.dataTransfer;
    if (!dt || dt.files.length) return; // files → native handler
    const text = dt.getData("text/plain");
    if (!text) return;
    const s = activeSession();
    if (s && s.ws.readyState === 1) {
      s.ws.send(enc.encode(text));
      s.term.focus();
    }
  });
}
