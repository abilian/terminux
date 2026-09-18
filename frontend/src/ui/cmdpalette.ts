// Shift+Cmd/Ctrl+P command launcher: verbs only, dispatched through the
// command bus. Separate from palette.ts (the quick switcher, which
// lists workspaces and tabs) but built on the same FuzzyOverlay.

import { invoke } from "../input/commands";
import { getState } from "../state/store";
import { createFuzzyOverlay, type FuzzyEntry } from "./fuzzyoverlay";

const overlay = createFuzzyOverlay("cmdpalette", "Run a command…");

interface CommandEntry {
  label: string;
  commandId: string;
  // If set, the entry is hidden unless the predicate returns true.
  // Used so e.g. "Sort by activity" only shows when there's more
  // than one workspace.
  visible?: () => boolean;
}

function buildEntries(): FuzzyEntry[] {
  const state = getState();
  const copyOn = state?.ui.copy_on_select ?? false;
  const sbOn = state?.ui.scrollback_persist ?? true;
  // Labels reflect the action that *will* run, not the current state,
  // so reading the label tells you what selecting it will do.
  const commands: CommandEntry[] = [
    { label: "Display usage stats", commandId: "view.stats" },
    {
      label: "Show remote connection URL",
      commandId: "view.connect-info",
    },
    {
      label: "Sort sidebar by activity (most used first)",
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
  ];
  return commands
    .filter((e) => e.visible === undefined || e.visible())
    .map((e) => ({ label: e.label, run: () => void invoke(e.commandId) }));
}

export function installCmdPalette(): void {
  overlay.install();
}

export function openCmdPalette(): void {
  overlay.open(buildEntries());
}

export function closeCmdPalette(): void {
  overlay.close();
}
