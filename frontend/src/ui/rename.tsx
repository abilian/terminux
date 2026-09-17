// Inline rename <input> as a component — window.prompt is unavailable in
// pywebview's WKWebView. Commits on Enter/blur, cancels on Escape. The
// input is uncontrolled, so the 2 s poll's re-render diffs past it without
// touching the value the user is typing.

import { useRef } from "preact/hooks";

interface Props {
  value: string;
  onCommit: (next: string) => void;
  onCancel: () => void;
}

export function RenameInput({ value, onCommit, onCancel }: Props) {
  const done = useRef(false);
  const finish = (el: HTMLInputElement, save: boolean): void => {
    if (done.current) {
      return;
    }
    done.current = true;
    const next = el.value.trim();
    if (save && next && next !== value) {
      onCommit(next);
    } else {
      onCancel();
    }
  };
  return (
    <input
      class="name-input"
      spellcheck={false}
      ref={(el) => {
        // Mount-only init: the ref callback re-fires on every diff, so the
        // dataset flag keeps later renders from resetting the value.
        // Synchronous focus+select: refs fire after DOM insertion, and a
        // deferred focus could land between the user's first keystrokes,
        // re-selecting and eating what they had typed.
        if (el && el.dataset.mounted !== "1") {
          el.dataset.mounted = "1";
          el.value = value;
          el.focus();
          el.select();
        }
      }}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") {
          finish(e.currentTarget, true);
        } else if (e.key === "Escape") {
          finish(e.currentTarget, false);
        }
      }}
      onBlur={(e) => finish(e.currentTarget, true)}
      onClick={(e) => e.stopPropagation()}
      onDblClick={(e) => e.stopPropagation()}
    />
  );
}
