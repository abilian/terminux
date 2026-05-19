// Minimal kitty keyboard protocol support. Apps like Claude Code only emit a
// distinct Shift+Enter when the terminal advertises kitty support and the app
// has pushed kitty flags (this is how cmux/Ghostty makes it work). xterm.js
// has no kitty support, so we observe the app's protocol traffic in the PTY
// output and answer it, then encode modified Enter ourselves.

export interface Kitty {
  flags: number;
  enabled: boolean;
  scan(bin: string, sendInput: (s: string) => void): string;
  encodeEnter(e: KeyboardEvent): string | null;
}

export function createKitty(): Kitty {
  // Matches CSI <intro> <params> u for ? (query) > (push) = (set) < (pop).
  const re = /\x1b\[([?>=<])([0-9;]*)u/g;
  return {
    flags: 0,
    enabled: false,
    scan(bin: string, sendInput: (s: string) => void): string {
      re.lastIndex = 0;
      let m: RegExpExecArray | null;
      let lastEnd = -1;
      while ((m = re.exec(bin)) !== null) {
        const intro = m[1];
        const n = parseInt(m[2], 10);
        if (intro === "?") {
          sendInput(`\x1b[?${this.flags}u`); // report current flags
        } else if (intro === ">" || intro === "=") {
          this.flags = Number.isNaN(n) ? 0 : n;
          this.enabled = true;
        } else if (intro === "<") {
          this.flags = 0;
          this.enabled = false;
        }
        lastEnd = re.lastIndex;
      }
      // Retain only an unprocessed tail so split sequences still match once.
      const keep = lastEnd >= 0 ? bin.slice(lastEnd) : bin;
      return keep.slice(-16);
    },
    encodeEnter(e: KeyboardEvent): string | null {
      if (!this.enabled) return null;
      const mod =
        1 +
        (e.shiftKey ? 1 : 0) +
        (e.altKey ? 2 : 0) +
        (e.ctrlKey ? 4 : 0) +
        (e.metaKey ? 8 : 0);
      if (mod === 1) return null; // plain Enter stays legacy CR
      return `\x1b[13;${mod}u`;
    },
  };
}
