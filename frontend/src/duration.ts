// Compact, no-locale-baggage duration formatting for activity stats.
//
// formatDuration(0)      → "0s"
// formatDuration(42)     → "42s"
// formatDuration(95)     → "1m 35s"
// formatDuration(3725)   → "1h 02m"
// formatDuration(90061)  → "25h 01m"
//
// Drops the seconds component once we're past an hour — the second-level
// detail isn't useful at that scale and the column stays narrow.

export function formatDuration(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return `${m}m ${String(r).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${String(rm).padStart(2, "0")}m`;
}
