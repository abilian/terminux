// Cmd/Ctrl+P quick switcher: fuzzy-jump to a workspace or tab.

import { api } from "./api";
import { fuzzyScore } from "./fuzzy";
import { activeSession, getState, refresh } from "./store";

interface Entry {
  label: string;
  run: () => void;
}

let overlay: HTMLDivElement | null = null;
let input: HTMLInputElement | null = null;
let listEl: HTMLDivElement | null = null;
let entries: Entry[] = [];
let filtered: Entry[] = [];
let selected = 0;

function buildEntries(): Entry[] {
  const state = getState();
  if (!state) return [];
  const out: Entry[] = [];
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
      if (!t) continue;
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

function render(): void {
  if (!listEl) return;
  const q = input?.value ?? "";
  filtered = entries
    .map((e) => ({ e, s: fuzzyScore(q, e.label) }))
    .filter((x): x is { e: Entry; s: number } => x.s !== null)
    .sort((a, b) => a.s - b.s)
    .slice(0, 50)
    .map((x) => x.e);
  if (selected >= filtered.length) selected = Math.max(0, filtered.length - 1);
  listEl.innerHTML = "";
  filtered.forEach((e, i) => {
    const row = document.createElement("div");
    row.className = "pal-row" + (i === selected ? " sel" : "");
    row.textContent = e.label;
    row.onclick = () => {
      e.run();
      closePalette();
    };
    listEl?.appendChild(row);
  });
}

function ensure(): void {
  if (overlay && input && listEl) return;
  overlay = document.createElement("div");
  overlay.id = "palette";
  overlay.hidden = true;
  input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Go to workspace or tab…";
  input.spellcheck = false;
  listEl = document.createElement("div");
  listEl.className = "pal-list";
  overlay.append(input, listEl);
  document.body.appendChild(overlay);

  input.addEventListener("input", () => {
    selected = 0;
    render();
  });
  input.addEventListener("keydown", (e: KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Escape") {
      closePalette();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      selected = Math.min(selected + 1, filtered.length - 1);
      render();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selected = Math.max(selected - 1, 0);
      render();
    } else if (e.key === "Enter") {
      const e0 = filtered[selected];
      if (e0) {
        e0.run();
        closePalette();
      }
    }
  });
}

export function installPalette(): void {
  ensure();
}

export function openPalette(): void {
  ensure();
  if (!overlay || !input) return;
  entries = buildEntries();
  selected = 0;
  input.value = "";
  render();
  overlay.hidden = false;
  input.focus();
}

export function closePalette(): void {
  if (overlay) overlay.hidden = true;
  activeSession()?.term.focus();
}
