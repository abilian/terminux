// Sidebar show/hide (Cmd/Ctrl+B) + draggable width. Both persist server-side
// (UiPrefs) so they survive an app exit — localStorage can't, since the
// loopback port (page origin) changes every launch.

import { send } from "../state/api";
import { getState } from "../state/store";
import { byId } from "../util/dom";

const MIN_W = 120;
const MAX_W = 600;

let hidden = false;

export function isSidebarHidden(): boolean {
  return hidden;
}

function setHidden(next: boolean, persist: boolean): void {
  hidden = next;
  byId("sidebar").style.display = hidden ? "none" : "flex";
  byId("divider").style.display = hidden ? "none" : "";
  if (persist) {
    void send("PATCH", "/ui", { sidebar_collapsed: hidden });
  }
  // The terminal area resized: the resize handler refits xterm and
  // re-renders the tab bar (its workspace chip shows with the sidebar off).
  window.dispatchEvent(new Event("resize"));
}

export function toggleSidebar(): void {
  setHidden(!hidden, true);
}

// Apply persisted width + collapsed state from server state (no re-persist).
export function applyLayout(): void {
  const ui = getState()?.ui;
  if (!ui) {
    return;
  }
  byId("sidebar").style.width = `${ui.sidebar_width}px`;
  if (ui.sidebar_collapsed) {
    setHidden(true, false);
  }
}

export function installSidebarResizer(): void {
  const divider = byId("divider");
  const sidebar = byId("sidebar");

  divider.addEventListener("mousedown", (down: MouseEvent) => {
    if (down.button !== 0) {
      return;
    }
    down.preventDefault();
    divider.classList.add("dragging");
    document.body.style.userSelect = "none";
    const left = sidebar.getBoundingClientRect().left;
    let width = sidebar.offsetWidth;

    const onMove = (e: MouseEvent): void => {
      width = Math.max(MIN_W, Math.min(MAX_W, Math.round(e.clientX - left)));
      sidebar.style.width = `${width}px`;
    };
    const onUp = (): void => {
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("mouseup", onUp, true);
      divider.classList.remove("dragging");
      document.body.style.userSelect = "";
      window.dispatchEvent(new Event("resize")); // refit xterm
      void send("PATCH", "/ui", { sidebar_width: width });
    };
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("mouseup", onUp, true);
  });
}
