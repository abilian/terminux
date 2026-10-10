// The two sidebar sorts. Pure functions of the workspace views, so the
// command handlers only apply the order they return.

import type { WorkspaceView } from "./types";

/** "Where did my time go?": most active time this session first. */
export function byTimeSpent(workspaces: WorkspaceView[]): WorkspaceView[] {
  return [...workspaces].sort((a, b) => b.active_seconds - a.active_seconds);
}

// Ready (green) first, then working (amber), then everything else.
function group(w: WorkspaceView): number {
  if (w.status === "unseen") {
    return 0;
  }
  return w.status === "busy" ? 1 : 2;
}

/**
 * "What needs me, and what was I just doing?": ready workspaces in the
 * order they finished (oldest first, like a queue), then working ones,
 * then the rest; within those two, the most recently typed-in first.
 * Never-used workspaces keep their place at the end (the sort is stable).
 */
export function byRecentActivity(workspaces: WorkspaceView[]): WorkspaceView[] {
  return [...workspaces].sort((a, b) => {
    const g = group(a) - group(b);
    if (g !== 0) {
      return g;
    }
    if (group(a) === 0) {
      return (a.ready_since ?? 0) - (b.ready_since ?? 0);
    }
    return (b.last_used_at ?? -Infinity) - (a.last_used_at ?? -Infinity);
  });
}
