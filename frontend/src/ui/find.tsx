// Find-in-terminal overlay (Cmd/Ctrl+F): a small input wired to xterm's
// SearchAddon. Enter / Shift+Enter step matches; Escape closes. The
// query persists between opens (re-selected, iTerm2-style), so the
// overlay is mounted once and only toggled.

import { render } from "preact";

import { activeSession } from "../state/store";

let host: HTMLDivElement | null = null;
let visible = false;

function rerender(): void {
  if (host) {
    render(<FindOverlay visible={visible} />, host);
  }
}

function ensure(): void {
  if (!host) {
    host = document.createElement("div");
  }
  if (!host.isConnected) {
    document.body.appendChild(host);
  }
  rerender();
}

export function installFind(): void {
  ensure();
}

export function openFind(): void {
  visible = true;
  ensure();
  const input = host?.querySelector("input");
  input?.focus();
  input?.select();
}

export function closeFind(): void {
  visible = false;
  rerender();
  activeSession()?.term.focus();
}

function FindOverlay({ visible: shown }: { visible: boolean }) {
  return (
    <div id="find" hidden={!shown}>
      <input
        type="text"
        placeholder="Find…"
        spellcheck={false}
        onInput={(e) => {
          const s = activeSession();
          const q = e.currentTarget.value;
          if (s && q) {
            s.search.findNext(q, { incremental: true });
          }
        }}
        onKeyDown={(e) => {
          e.stopPropagation(); // don't let global shortcuts see typing here
          const s = activeSession();
          const q = e.currentTarget.value;
          if (e.key === "Escape") {
            closeFind();
          } else if (e.key === "Enter" && s && q) {
            if (e.shiftKey) {
              s.search.findPrevious(q);
            } else {
              s.search.findNext(q);
            }
          }
        }}
      />
    </div>
  );
}
