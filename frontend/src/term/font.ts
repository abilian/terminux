// Terminal font zoom, persisted server-side (UiPrefs) so it survives an
// app exit — localStorage can't, because the loopback port (and thus the
// page origin) changes every launch.

import { send } from "../state/api";
import { getState, sessions } from "../state/store";

const FONT_MIN = 6;
const FONT_MAX = 32;
const DEFAULT = 13;

let fontSize = DEFAULT;

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

// Adopt the persisted size. main.ts calls it once, before the first
// terminal opens; later polls must not, or they'd revert a zoom in flight.
export function syncFontFromState(): void {
  const f = getState()?.ui.font_size;
  if (f) {
    fontSize = clamp(f);
    applyToSessions();
  }
}

export function resetFontSize(): void {
  applyFontSize(DEFAULT);
}

export function applyFontSize(next: number): void {
  fontSize = clamp(next);
  applyToSessions();
  void send("PATCH", "/ui", { font_size: fontSize });
}
