// Shared fuzzy-filtered overlay behind both palettes (the Cmd/Ctrl+P
// quick switcher and the Shift+Cmd/Ctrl+P command launcher): an input,
// a ranked row list, arrow/Enter/Escape keyboard handling. Each palette
// supplies its id, placeholder, and entries; everything else lives here
// once. Remounted per open (keyed) so the query always starts empty.

import { render } from "preact";
import { useState } from "preact/hooks";

import { activeSession } from "../state/store";
import { fuzzyScore } from "../util/fuzzy";

export interface FuzzyEntry {
  label: string;
  run: () => void;
}

interface OverlayApi {
  install: () => void;
  open: (entries: FuzzyEntry[]) => void;
  close: () => void;
}

export function createFuzzyOverlay(
  id: string,
  placeholder: string,
): OverlayApi {
  let host: HTMLDivElement | null = null;
  let entries: FuzzyEntry[] = [];
  let visible = false;
  let epoch = 0;

  const close = (): void => {
    visible = false;
    rerender();
    activeSession()?.term.focus();
  };

  function rerender(): void {
    if (host) {
      render(
        <Overlay
          key={epoch}
          id={id}
          placeholder={placeholder}
          entries={entries}
          visible={visible}
          onClose={close}
        />,
        host,
      );
    }
  }

  const ensure = (): void => {
    if (!host) {
      host = document.createElement("div");
    }
    if (!host.isConnected) {
      document.body.appendChild(host);
    }
    rerender();
  };

  return {
    install: ensure,
    open: (next: FuzzyEntry[]): void => {
      entries = next;
      visible = true;
      epoch++; // remount: fresh query, selection, and input focus
      ensure();
    },
    close,
  };
}

interface OverlayProps {
  id: string;
  placeholder: string;
  entries: FuzzyEntry[];
  visible: boolean;
  onClose: () => void;
}

function Overlay({ id, placeholder, entries, visible, onClose }: OverlayProps) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const filtered = entries
    .map((e) => ({ e, s: fuzzyScore(query, e.label) }))
    .filter((x): x is { e: FuzzyEntry; s: number } => x.s !== null)
    .sort((a, b) => a.s - b.s)
    .slice(0, 50)
    .map((x) => x.e);
  const sel = Math.min(selected, Math.max(0, filtered.length - 1));

  const pick = (e: FuzzyEntry): void => {
    e.run();
    onClose();
  };

  return (
    <div id={id} hidden={!visible}>
      <input
        type="text"
        placeholder={placeholder}
        spellcheck={false}
        ref={(el) => {
          // Mount-only (the overlay is remounted per open): grab focus.
          if (el && el.dataset.mounted !== "1") {
            el.dataset.mounted = "1";
            el.focus();
          }
        }}
        onInput={(e) => {
          setQuery(e.currentTarget.value);
          setSelected(0);
        }}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") {
            onClose();
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            setSelected(Math.min(sel + 1, filtered.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setSelected(Math.max(sel - 1, 0));
          } else if (e.key === "Enter") {
            const entry = filtered[sel];
            if (entry) {
              pick(entry);
            }
          }
        }}
      />
      <div class="pal-list">
        {filtered.map((e, i) => (
          <div
            key={e.label}
            class={"pal-row" + (i === sel ? " sel" : "")}
            onClick={() => pick(e)}
          >
            {e.label}
          </div>
        ))}
      </div>
    </div>
  );
}
