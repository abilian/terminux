// Usage-stats overlay opened by the command palette's "Display usage
// stats": every workspace ranked by active-session time, with a relative
// bar showing each one's share of the busiest. Rendered as a Preact
// island; while open it re-renders from the 2 s poll, so the numbers
// tick live instead of freezing at open time.

import { getState } from "../state/store";
import { formatDuration } from "../util/duration";
import { createOverlay } from "./overlay";

function elapsedSince(epochSecs: number): string {
  // Wall-clock delta between *now* and the session start — matches the
  // user's intuition for "how long has this session been going".
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - epochSecs));
  return formatDuration(secs);
}

const overlay = createOverlay((visible, key) => (
  <StatsOverlay key={key} visible={visible} />
));

export const installStatsPanel = overlay.install;
export const openStatsPanel = overlay.open;
export const closeStatsPanel = overlay.close;

// Called from the render hook: keeps the numbers live while open.
export function renderStatsPanel(): void {
  if (overlay.isVisible()) {
    overlay.rerender();
  }
}

function StatsOverlay({ visible: shown }: { visible: boolean }) {
  const state = getState();
  const workspaces = state?.workspaces ?? [];
  const total = workspaces.reduce((s, w) => s + w.active_seconds, 0);
  const ranked = [...workspaces].sort(
    (a, b) => b.active_seconds - a.active_seconds,
  );
  const max = ranked[0]?.active_seconds ?? 0;
  return (
    <div
      id="stats-overlay"
      hidden={!shown}
      onClick={(e) => {
        // Click on the backdrop (not the card) dismisses.
        if (e.target === e.currentTarget) {
          closeStatsPanel();
        }
      }}
    >
      <div
        id="stats-card"
        // Focusable so Escape lands here, not on the still-focused xterm
        // textarea (which would otherwise feed ESC to the shell).
        tabIndex={-1}
        ref={(el) => {
          if (el && el.dataset.mounted !== "1") {
            el.dataset.mounted = "1";
            el.focus();
          }
        }}
      >
        <div class="stats-header">
          <div class="stats-title">Workspace activity</div>
          {state && (
            <div class="stats-meta">
              {`session started ${elapsedSince(state.session_started_at)} ago` +
                ` · ${formatDuration(total)} active`}
            </div>
          )}
        </div>
        <div class="stats-body">
          {ranked.length === 0 || total === 0 ? (
            <div class="stats-empty">
              No keystrokes recorded yet in this session — type into a workspace
              to start accruing time.
            </div>
          ) : (
            ranked.map((w) => (
              <div key={w.id} class="stats-row">
                <div class="stats-name">{w.name}</div>
                <div class="stats-bar">
                  <div
                    class="stats-bar-fill"
                    style={{
                      width:
                        max > 0
                          ? `${Math.round((w.active_seconds / max) * 100)}%`
                          : "0%",
                    }}
                  />
                </div>
                <div class="stats-time">{formatDuration(w.active_seconds)}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
