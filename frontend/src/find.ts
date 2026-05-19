// Find-in-terminal overlay (Cmd/Ctrl+F): a small input wired to xterm's
// SearchAddon. Enter / Shift+Enter step matches; Escape closes.

import { activeSession } from "./store";

let overlay: HTMLDivElement | null = null;
let input: HTMLInputElement | null = null;

function ensure(): void {
  if (overlay && input) return;
  overlay = document.createElement("div");
  overlay.id = "find";
  overlay.hidden = true;
  input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Find…";
  input.spellcheck = false;
  overlay.appendChild(input);
  document.body.appendChild(overlay);

  input.addEventListener("input", () => {
    const s = activeSession();
    if (s && input && input.value) {
      s.search.findNext(input.value, { incremental: true });
    }
  });
  input.addEventListener("keydown", (e: KeyboardEvent) => {
    e.stopPropagation(); // don't let global shortcuts see typing here
    const s = activeSession();
    if (e.key === "Escape") {
      closeFind();
    } else if (e.key === "Enter" && s && input && input.value) {
      if (e.shiftKey) s.search.findPrevious(input.value);
      else s.search.findNext(input.value);
    }
  });
}

export function installFind(): void {
  ensure();
}

export function openFind(): void {
  ensure();
  if (!overlay || !input) return;
  overlay.hidden = false;
  input.focus();
  input.select();
}

export function closeFind(): void {
  if (overlay) overlay.hidden = true;
  activeSession()?.term.focus();
}
