// Entry point: wire the render/activate hooks, global listeners, and the
// background status poll, then do the first refresh.

import "./style.css";

import { invoke } from "./input/commands";
import { installCommands } from "./input/commands-bindings";
import { installDragAndDrop } from "./ui/dragdrop";
import { syncFontFromState } from "./term/font";
import { installShortcuts } from "./input/keymap";
import { renderStatsPanel } from "./ui/statspanel";
import { isReordering } from "./ui/reorder";
import { applyLayout, installSidebarResizer } from "./ui/layout";
import { renderSidebar } from "./ui/sidebar";
import {
  activeSession,
  activeWorkspace,
  configure,
  getState,
  poll,
  refresh,
  sessions,
} from "./state/store";
import {
  ensureActiveTerminal,
  installOwnershipClaims,
  installScrollbackAutosave,
} from "./term/terminal";
import { renderTabs } from "./ui/tabs";
import { byId } from "./util/dom";

configure({
  onRender: () => {
    // Window/browser-tab title carries the workspace name too — the only
    // cue that works even when the app is in the background.
    const ws = activeWorkspace();
    document.title = ws ? `${ws.name} — terminux` : "terminux";
    // The islands diff the DOM, so a rename in progress survives the
    // 2 s poll on its own. Only a live drag still pauses rendering:
    // the drop-marker classes are managed imperatively by reorder.ts,
    // and a diff would overwrite them.
    if (isReordering()) {
      return;
    }
    renderSidebar();
    renderTabs();
    renderStatsPanel(); // the stats overlay ticks live while open
  },
  onActivate: () => ensureActiveTerminal(),
});

byId("new-ws").onclick = (): void => {
  invoke("workspace.new");
};

window.addEventListener("resize", () => {
  activeSession()?.fit.fit();
  renderTabs(); // a sidebar toggle shows or hides the workspace chip
});

// Must come before any surface that calls ``invoke()`` — keymap and
// the palettes both dispatch through the bus.
installCommands();
installSidebarResizer();
installShortcuts();
installDragAndDrop();
installScrollbackAutosave();
installOwnershipClaims();

// Light status polling so sidebar dots reflect background activity. A
// transient network error (backend stall, sleeping laptop) never kills the
// poll (``poll`` keeps the last state); a render error reaches the console.
setInterval(() => {
  void poll();
}, 2000);

// E2E hook: lets Playwright reach live sessions (e.g. sever a websocket to
// exercise the reconnect path).
(window as unknown as { __terminux: object }).__terminux = { sessions };

// First load: render, adopt the persisted font and layout, and only then
// open the active terminal (refresh activates it). Retried until the state
// arrives, so a failed first fetch doesn't lose the persisted font size.
async function firstLoad(): Promise<void> {
  await poll();
  while (getState() === null) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await poll();
  }
  syncFontFromState();
  applyLayout();
  await refresh();
}
void firstLoad();
