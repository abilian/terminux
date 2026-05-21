// Shift+Cmd/Ctrl+P command launcher: verbs only.
//
// Deliberately separate from palette.ts (the Cmd/Ctrl+P quick switcher,
// which lists workspaces and tabs). This one lists actions you can run:
// reorder by activity, reset counters, toggle prefs, open the stats
// overlay. Fuzzy-filter on input.

import { api } from "./api";
import { fuzzyScore } from "./fuzzy";
import { openStatsPanel } from "./statspanel";
import { activeSession, getState, refresh } from "./store";

interface Command {
  label: string;
  run: () => void;
}

let overlay: HTMLDivElement | null = null;
let input: HTMLInputElement | null = null;
let listEl: HTMLDivElement | null = null;
let commands: Command[] = [];
let filtered: Command[] = [];
let selected = 0;

function buildCommands(): Command[] {
  const state = getState();
  const out: Command[] = [];

  out.push({
    label: "Display usage stats",
    run: () => openStatsPanel(),
  });

  if (state && state.workspaces.length > 1) {
    out.push({
      label: "Reorder sidebar by activity (most used first)",
      run: () => {
        const order = [...state.workspaces]
          .sort((a, b) => b.active_seconds - a.active_seconds)
          .map((w) => w.id);
        const target = order[0];
        if (!target) return;
        api(`/workspaces/${target}`, {
          method: "PATCH",
          body: JSON.stringify({ order }),
        }).then(refresh);
      },
    });
  }

  out.push({
    label: "Reset session activity counters",
    run: () => {
      api("/activity/reset", { method: "POST" }).then(refresh);
    },
  });

  // Pref toggles — label reflects the action that's available, not the
  // current state, so reading the label tells you what selecting it will do.
  if (state) {
    const copyOn = state.ui.copy_on_select;
    out.push({
      label: copyOn
        ? "Disable auto-copy on selection"
        : "Enable auto-copy on selection",
      run: () => {
        api("/ui", {
          method: "PATCH",
          body: JSON.stringify({ copy_on_select: !copyOn }),
        }).then(refresh);
      },
    });
    const sbOn = state.ui.scrollback_persist;
    out.push({
      label: sbOn
        ? "Disable scrollback persistence"
        : "Enable scrollback persistence",
      run: () => {
        api("/ui", {
          method: "PATCH",
          body: JSON.stringify({ scrollback_persist: !sbOn }),
        }).then(refresh);
      },
    });
  }

  return out;
}

function render(): void {
  if (!listEl) return;
  const q = input?.value ?? "";
  filtered = commands
    .map((c) => ({ c, s: fuzzyScore(q, c.label) }))
    .filter((x): x is { c: Command; s: number } => x.s !== null)
    .sort((a, b) => a.s - b.s)
    .slice(0, 50)
    .map((x) => x.c);
  if (selected >= filtered.length) selected = Math.max(0, filtered.length - 1);
  listEl.innerHTML = "";
  filtered.forEach((c, i) => {
    const row = document.createElement("div");
    row.className = "pal-row" + (i === selected ? " sel" : "");
    row.textContent = c.label;
    row.onclick = () => {
      c.run();
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
      const c0 = filtered[selected];
      if (c0) {
        c0.run();
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
  commands = buildCommands();
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
