// Entry point: wire the render/activate hooks, global listeners, and the
// background status poll, then do the first refresh.

import "./style.css";

import { api } from "./api";
import { installCmdPalette } from "./cmdpalette";
import { installDragAndDrop } from "./dragdrop";
import { installFind } from "./find";
import { syncFontFromState } from "./font";
import { installShortcuts } from "./keymap";
import { installPalette } from "./palette";
import { installStatsPanel } from "./statspanel";
import { isReordering } from "./reorder";
import { applyLayout, installSidebarResizer } from "./layout";
import { renderSidebar } from "./sidebar";
import { activeWorkspace, configure, poll, refresh, sessions } from "./store";
import { ensureActiveTerminal, installScrollbackAutosave } from "./terminal";
import { renderTabs } from "./tabs";

configure({
  onRender: () => {
    syncFontFromState(); // before the first terminal opens; one-shot
    if (isReordering()) return; // don't rebuild rows mid-drag
    renderSidebar();
    renderTabs();
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
  if (s) s.fit.fit();
});

installSidebarResizer();
installFind();
installPalette();
installCmdPalette();
installStatsPanel();
installShortcuts();
installDragAndDrop();
installScrollbackAutosave();

// Light status polling so sidebar dots reflect background activity.
setInterval(() => {
  void poll();
}, 2000);

void refresh().then(applyLayout);
