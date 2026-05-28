// Shift+Cmd/Ctrl+P command launcher: verbs only.
//
// Deliberately separate from palette.ts (the Cmd/Ctrl+P quick switcher,
// which lists workspaces and tabs). This one is a list of fixed actions
// dispatched through the shared command bus in ./commands.ts — same
// dispatch table the keyboard and the native menu use.

import { invoke } from "./commands";
import { fuzzyScore } from "./fuzzy";
import { activeSession, getState } from "./store";

interface PaletteEntry {
  label: string;
  commandId: string;
  // If set, the entry is hidden unless the predicate returns true.
  // Used so e.g. "Reorder by activity" only shows when there's more
  // than one workspace.
  visible?: () => boolean;
}

let overlay: HTMLDivElement | null = null;
let input: HTMLInputElement | null = null;
let listEl: HTMLDivElement | null = null;
let entries: PaletteEntry[] = [];
let filtered: PaletteEntry[] = [];
let selected = 0;

function buildEntries(): PaletteEntry[] {
  const state = getState();
  const copyOn = state?.ui.copy_on_select ?? false;
  const sbOn = state?.ui.scrollback_persist ?? true;
  // Labels reflect the action that *will* run, not the current state,
  // so reading the label tells you what selecting it will do.
  return [
    { label: "Display usage stats", commandId: "view.stats" },
    {
      label: "Reorder sidebar by activity (most used first)",
      commandId: "workspace.reorder-by-activity",
      visible: () => (getState()?.workspaces.length ?? 0) > 1,
    },
    {
      label: "Reset session activity counters",
      commandId: "view.activity.reset",
    },
    {
      label: copyOn
        ? "Disable auto-copy on selection"
        : "Enable auto-copy on selection",
      commandId: "view.copy-on-select.toggle",
    },
    {
      label: sbOn
        ? "Disable scrollback persistence"
        : "Enable scrollback persistence",
      commandId: "view.scrollback-persist.toggle",
    },
  ].filter((e) => e.visible === undefined || e.visible());
}

function render(): void {
  if (!listEl) return;
  const q = input?.value ?? "";
  filtered = entries
    .map((e) => ({ e, s: fuzzyScore(q, e.label) }))
    .filter((x): x is { e: PaletteEntry; s: number } => x.s !== null)
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
      invoke(e.commandId);
      closeCmdPalette();
    };
    listEl?.appendChild(row);
  });
}

function ensure(): void {
  if (overlay && input && listEl) return;
  overlay = document.createElement("div");
  overlay.id = "cmdpalette";
  overlay.hidden = true;
  input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Run a command…";
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
      closeCmdPalette();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      selected = Math.min(selected + 1, filtered.length - 1);
      render();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selected = Math.max(selected - 1, 0);
      render();
    } else if (e.key === "Enter") {
      const sel = filtered[selected];
      if (sel) {
        invoke(sel.commandId);
        closeCmdPalette();
      }
    }
  });
}

export function installCmdPalette(): void {
  ensure();
}

export function openCmdPalette(): void {
  ensure();
  if (!overlay || !input) return;
  entries = buildEntries();
  selected = 0;
  input.value = "";
  render();
  overlay.hidden = false;
  input.focus();
}

export function closeCmdPalette(): void {
  if (overlay) overlay.hidden = true;
  activeSession()?.term.focus();
}
