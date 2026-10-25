// Find-in-terminal overlay (Cmd/Ctrl+F): a small input wired to xterm's
// SearchAddon. Enter / Shift+Enter step matches; Escape closes. The
// query persists between opens (re-selected, iTerm2-style), so the card
// ignores the overlay's per-open key and is only toggled.

import { useLayoutEffect, useRef } from "preact/hooks";

import { activeSession } from "../state/store";
import { createOverlay } from "./overlay";

const overlay = createOverlay((visible) => <FindOverlay visible={visible} />);

export const openFind = overlay.open;

function FindOverlay({ visible }: { visible: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    if (visible) {
      input.current?.focus();
      input.current?.select();
    }
  }, [visible]);
  return (
    <div id="find" hidden={!visible}>
      <input
        ref={input}
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
          if (e.key === "Enter" && s && q) {
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
