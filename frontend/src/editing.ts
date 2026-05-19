// macOS line/word editing chords (iTerm2 "natural text editing"). Webviews
// otherwise send nothing for Cmd/Option+Arrows (and Cmd+Left may even trigger
// back-navigation), so shells and Claude Code can't move by line/word.
// Returns the bytes to send, or null if this isn't an editing chord.

export function macEditingSeq(e: KeyboardEvent): string | null {
  if (e.ctrlKey || e.shiftKey) return null; // Shift+Cmd/Opt+Arrow = navigation
  const cmd = e.metaKey && !e.altKey;
  const opt = e.altKey && !e.metaKey;
  if (cmd) {
    if (e.key === "ArrowLeft") return "\x01"; // Ctrl-A: start of line
    if (e.key === "ArrowRight") return "\x05"; // Ctrl-E: end of line
    if (e.key === "Backspace") return "\x15"; // Ctrl-U: kill to line start
  } else if (opt) {
    if (e.key === "ArrowLeft") return "\x1bb"; // ESC b: word back
    if (e.key === "ArrowRight") return "\x1bf"; // ESC f: word forward
    if (e.key === "Backspace") return "\x17"; // Ctrl-W: kill previous word
    if (e.key === "Delete") return "\x1bd"; // ESC d: kill next word
  }
  return null;
}
