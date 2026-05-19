// Tiny case-insensitive subsequence fuzzy matcher. Returns a score where
// lower is better (fewer/smaller gaps), or null if `query` doesn't match.

export function fuzzyScore(query: string, text: string): number | null {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (!q) return 0;
  let from = 0;
  let score = 0;
  let last = -1;
  for (const ch of q) {
    const idx = t.indexOf(ch, from);
    if (idx < 0) return null;
    score += idx - last - 1; // characters skipped (gap) before this match
    last = idx;
    from = idx + 1;
  }
  return score + text.length * 0.001; // tie-break: prefer shorter labels
}
