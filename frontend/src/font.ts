// Terminal font zoom, persisted server-side (UiPrefs) so it survives an
// app exit — localStorage can't, because the loopback port (and thus the
// page origin) changes every launch.

import { api } from "./api";
import { getState, sessions } from "./store";

const FONT_MIN = 6;
const FONT_MAX = 32;
const DEFAULT = 13;

let fontSize = DEFAULT;
let initialized = false;

const clamp = (n: number): number => Math.max(FONT_MIN, Math.min(FONT_MAX, n));

export function getFontSize(): number {
  return fontSize;
}

function applyToSessions(): void {
  for (const s of sessions.values()) {
    s.term.options.fontSize = fontSize;
    s.fit.fit();
  }
}

// Adopt the persisted size once, before the first terminal opens. Idempotent
// and one-shot so a later poll can't revert an in-flight zoom change.
export function syncFontFromState(): void {
  if (initialized) return;
  const f = getState()?.ui.font_size;
  if (f) {
    fontSize = clamp(f);
    applyToSessions();
  }
  initialized = true;
}

export function resetFontSize(): void {
  applyFontSize(DEFAULT);
}

export function applyFontSize(next: number): void {
  initialized = true; // user changed it explicitly; don't let sync override
  fontSize = clamp(next);
  applyToSessions();
  api("/ui", {
    method: "PATCH",
    body: JSON.stringify({ font_size: fontSize }),
  });
}
