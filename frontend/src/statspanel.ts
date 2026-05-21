// Usage-stats overlay opened by the command palette's "Display usage stats".
//
// A focused page (no chrome, esc/click-out to close) listing every
// workspace ranked by active-session time, with a relative bar showing
// each one's share of the busiest. Header reports the session's total
// wall-clock age. Read-only — actions live in the command palette.

import { formatDuration } from "./duration";
import { activeSession, getState } from "./store";

let overlay: HTMLDivElement | null = null;
let card: HTMLDivElement | null = null;
let bodyEl: HTMLDivElement | null = null;
let headerEl: HTMLDivElement | null = null;

function elapsedSince(epoch: number): string {
  // Wall-clock delta between *now* and the session start. Matches the
  // user's intuition for "how long has this session been going" — uses
  // Date.now() rather than monotonic time which the backend uses for
  // accrual.
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  return formatDuration(secs);
}

function render(): void {
  if (!bodyEl || !headerEl) return;
  const state = getState();
  if (!state) {
    bodyEl.textContent = "";
    headerEl.textContent = "";
    return;
  }

  const total = state.workspaces.reduce((s, w) => s + w.active_seconds, 0);
  headerEl.innerHTML = "";
  const title = document.createElement("div");
  title.className = "stats-title";
  title.textContent = "Workspace activity";
  const meta = document.createElement("div");
  meta.className = "stats-meta";
  meta.textContent =
    `session started ${elapsedSince(state.session_started_at)} ago` +
    ` · ${formatDuration(total)} active`;
  headerEl.append(title, meta);

  const ranked = [...state.workspaces].sort(
    (a, b) => b.active_seconds - a.active_seconds,
  );
  const max = ranked[0]?.active_seconds ?? 0;

  bodyEl.innerHTML = "";
  if (ranked.length === 0 || total === 0) {
    const empty = document.createElement("div");
    empty.className = "stats-empty";
    empty.textContent =
      "No keystrokes recorded yet in this session — type into a workspace " +
      "to start accruing time.";
    bodyEl.appendChild(empty);
    return;
  }

  for (const w of ranked) {
    const row = document.createElement("div");
    row.className = "stats-row";

    const name = document.createElement("div");
    name.className = "stats-name";
    name.textContent = w.name;
    row.appendChild(name);

    const bar = document.createElement("div");
    bar.className = "stats-bar";
    const fill = document.createElement("div");
    fill.className = "stats-bar-fill";
    fill.style.width =
      max > 0 ? `${Math.round((w.active_seconds / max) * 100)}%` : "0%";
    bar.appendChild(fill);
    row.appendChild(bar);

    const time = document.createElement("div");
    time.className = "stats-time";
    time.textContent = formatDuration(w.active_seconds);
    row.appendChild(time);

    bodyEl.appendChild(row);
  }
}

function ensure(): void {
  if (overlay && card && bodyEl && headerEl) return;
  overlay = document.createElement("div");
  overlay.id = "stats-overlay";
  overlay.hidden = true;
  overlay.addEventListener("click", (e) => {
    // Click on the backdrop (not the card) dismisses.
    if (e.target === overlay) closeStatsPanel();
  });

  card = document.createElement("div");
  card.id = "stats-card";
  headerEl = document.createElement("div");
  headerEl.className = "stats-header";
  bodyEl = document.createElement("div");
  bodyEl.className = "stats-body";
  card.append(headerEl, bodyEl);
  overlay.appendChild(card);
  document.body.appendChild(overlay);

  document.addEventListener("keydown", (e) => {
    if (overlay?.hidden) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      closeStatsPanel();
    }
  });
}

export function installStatsPanel(): void {
  ensure();
}

export function openStatsPanel(): void {
  ensure();
  if (!overlay) return;
  render();
  overlay.hidden = false;
}

export function closeStatsPanel(): void {
  if (overlay) overlay.hidden = true;
  activeSession()?.term.focus();
}
