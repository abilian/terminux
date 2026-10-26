// Find-in-terminal overlay (Cmd/Ctrl+F): a small input wired to xterm's
// SearchAddon. Enter / Shift+Enter step matches; Escape in it closes. Not
// modal: the terminal keeps working (and keeps its Escape) while it's
// open. The query persists between opens (re-selected, iTerm2-style), so
// the card isn't remounted per open; each open re-focuses it.

import { useLayoutEffect, useRef } from "preact/hooks";

import { activeSession } from "../state/store";
import { createOverlay } from "./overlay";

const overlay = createOverlay(
  (visible, opened) => <FindOverlay visible={visible} opened={opened} />,
  { modal: false },
);

export const openFind = overlay.open;

function FindOverlay({
  visible,
  opened,
}: {
  visible: boolean;
  opened: number;
}) {
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    if (visible) {
      input.current?.focus();
      input.current?.select();
    }
  }, [visible, opened]); // Cmd/Ctrl+F while open re-focuses it
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
          if (e.key === "Escape") {
            overlay.close();
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
