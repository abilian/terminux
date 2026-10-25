// Shared fuzzy-filtered overlay behind both palettes (the quick switcher
// and the command launcher): an input, a ranked row list, arrow/Enter
// keyboard handling. Each palette supplies its id, placeholder, and
// entries; everything else lives here once. Remounted per open (keyed) so
// the query always starts empty.

import { useLayoutEffect, useRef, useState } from "preact/hooks";

import { fuzzyScore } from "../util/fuzzy";
import { createOverlay } from "./overlay";

export interface FuzzyEntry {
  label: string;
  run: () => void;
}

export function createFuzzyOverlay(
  id: string,
  placeholder: string,
): { open: (entries: FuzzyEntry[]) => void } {
  let entries: FuzzyEntry[] = [];
  const overlay = createOverlay((visible, key) => (
    <Overlay
      key={key}
      id={id}
      placeholder={placeholder}
      entries={entries}
      visible={visible}
      onClose={() => overlay.close()}
    />
  ));
  return {
    open: (next: FuzzyEntry[]): void => {
      entries = next;
      overlay.open();
    },
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
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => input.current?.focus(), []); // remounted per open
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
        ref={input}
        type="text"
        placeholder={placeholder}
        spellcheck={false}
        onInput={(e) => {
          setQuery(e.currentTarget.value);
          setSelected(0);
        }}
        onKeyDown={(e) => {
          e.stopPropagation(); // don't let global shortcuts see typing here
          if (e.key === "ArrowDown") {
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
