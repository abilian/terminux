// Cmd/Ctrl+P quick switcher: fuzzy-jump to a workspace or tab. The
// overlay/keyboard machinery is the shared FuzzyOverlay; this module
// only knows how to turn app state into jump entries.

import { api } from "../state/api";
import { getState, refresh } from "../state/store";
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
      run: () => {
        api(`/workspaces/${w.id}`, {
          method: "PATCH",
          body: JSON.stringify({ active: true }),
        }).then(refresh);
      },
    });
    for (const tid of w.tab_ids) {
      const t = state.tabs[tid];
      if (!t) {
        continue;
      }
      out.push({
        label: `  ${t.title} — ${w.name}`,
        run: () => {
          api(`/workspaces/${w.id}`, {
            method: "PATCH",
            body: JSON.stringify({ active: true, active_tab_id: tid }),
          }).then(refresh);
        },
      });
    }
  }
  return out;
}

export function installPalette(): void {
  overlay.install();
}

export function openPalette(): void {
  overlay.open(buildEntries());
}

export function closePalette(): void {
  overlay.close();
}
