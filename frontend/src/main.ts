// Entry point: wire the render/activate hooks, global listeners, and the
// background status poll, then do the first refresh.

import "./style.css";

import { api } from "./state/api";
import { installCommands } from "./input/commands-bindings";
import { installCmdPalette } from "./ui/cmdpalette";
import { installDragAndDrop } from "./ui/dragdrop";
import { installFind } from "./ui/find";
import { syncFontFromState } from "./term/font";
import { installShortcuts } from "./input/keymap";
import { installPalette } from "./ui/palette";
import { installConnectInfo } from "./ui/connectinfo";
import { installStatsPanel, renderStatsPanel } from "./ui/statspanel";
import { isReordering } from "./ui/reorder";
import { applyLayout, installSidebarResizer } from "./ui/layout";
import { renderSidebar } from "./ui/sidebar";
import {
  activeWorkspace,
  configure,
  poll,
  refresh,
  sessions,
} from "./state/store";
import {
  ensureActiveTerminal,
  installScrollbackAutosave,
} from "./term/terminal";
import { renderTabs } from "./ui/tabs";

configure({
  onRender: () => {
    // Window/browser-tab title carries the workspace name too — the only
    // cue that works even when the app is in the background.
    const ws = activeWorkspace();
    document.title = ws ? `${ws.name} — terminux` : "terminux";
    syncFontFromState(); // before the first terminal opens; one-shot
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

const newWs = document.getElementById("new-ws");
if (newWs) {
  newWs.onclick = (): void => {
    api("/workspaces", { method: "POST" }).then(refresh);
  };
}

window.addEventListener("resize", () => {
  const ws = activeWorkspace();
  const s = ws?.active_tab_id ? sessions.get(ws.active_tab_id) : null;
  if (s) {
    s.fit.fit();
  }
});

// Must come before any surface that calls ``invoke()`` — keymap and
// the palettes both dispatch through the bus.
installCommands();
installSidebarResizer();
installFind();
installPalette();
installCmdPalette();
installStatsPanel();
installConnectInfo();
installShortcuts();
installDragAndDrop();
installScrollbackAutosave();

// Light status polling so sidebar dots reflect background activity. A
// transient network error (backend stall, sleeping laptop) must never kill
// the poll — terminals reconnect on their own; the sidebar just goes stale
// until the next successful poll.
setInterval(() => {
  void poll().catch(() => {});
}, 2000);

// E2E hook: lets Playwright reach live sessions (e.g. sever a websocket to
// exercise the reconnect path).
(window as unknown as { __terminux: object }).__terminux = { sessions };

void refresh().then(() => {
  applyLayout();
  renderTabs(); // applyLayout may have just hidden the sidebar → chip
});
