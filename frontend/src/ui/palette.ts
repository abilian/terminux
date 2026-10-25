// Cmd/Ctrl+P quick switcher: fuzzy-jump to a workspace or tab. The
// overlay/keyboard machinery is the shared FuzzyOverlay; this module
// only knows how to turn app state into jump entries.

import { activateOptimistic, getState } from "../state/store";
import { createFuzzyOverlay, type FuzzyEntry } from "./fuzzyoverlay";

const overlay = createFuzzyOverlay("palette", "Go to workspace or tab…");

function buildEntries(): FuzzyEntry[] {
  const state = getState();
  if (!state) {
    return [];
  }
  const out: FuzzyEntry[] = [];
  for (const w of state.workspaces) {
    out.push({
      label: `◆ ${w.name}`,
      run: () => void activateOptimistic(w.id),
    });
    for (const tid of w.tab_ids) {
      const t = state.tabs[tid];
      if (!t) {
        continue;
      }
      out.push({
        label: `  ${t.title} — ${w.name}`,
        run: () => void activateOptimistic(w.id, tid),
      });
    }
  }
  return out;
}

export function openPalette(): void {
  overlay.open(buildEntries());
}
