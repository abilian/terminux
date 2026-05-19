// Sidebar show/hide (Cmd/Ctrl+B) + draggable width. Both persist server-side
// (UiPrefs) so they survive an app exit — localStorage can't, since the
// loopback port (page origin) changes every launch.

import { api } from "./api";
import { getState } from "./store";

const MIN_W = 120;
const MAX_W = 600;

function setHidden(hidden: boolean, persist: boolean): void {
  const el = document.getElementById("sidebar");
  const divider = document.getElementById("divider");
  if (!el) return;
  el.style.display = hidden ? "none" : "flex";
  if (divider) divider.style.display = hidden ? "none" : "";
  if (persist) {
    api("/ui", {
      method: "PATCH",
      body: JSON.stringify({ sidebar_collapsed: hidden }),
    });
  }
  // The terminal area resized — let the resize handler refit xterm.
  window.dispatchEvent(new Event("resize"));
}

export function toggleSidebar(): void {
  const el = document.getElementById("sidebar");
  setHidden(el?.style.display !== "none", true);
}

// Apply persisted width + collapsed state from server state (no re-persist).
export function applyLayout(): void {
  const ui = getState()?.ui;
  if (!ui) return;
  const el = document.getElementById("sidebar");
  if (el && ui.sidebar_width) el.style.width = `${ui.sidebar_width}px`;
  if (ui.sidebar_collapsed) setHidden(true, false);
}

export function installSidebarResizer(): void {
  const divider = document.getElementById("divider");
  const sidebar = document.getElementById("sidebar");
  if (!divider || !sidebar) return;

  divider.addEventListener("mousedown", (down: MouseEvent) => {
    if (down.button !== 0) return;
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
      api("/ui", {
        method: "PATCH",
        body: JSON.stringify({ sidebar_width: width }),
      });
    };
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("mouseup", onUp, true);
  });
}
