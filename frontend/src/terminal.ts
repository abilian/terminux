// xterm session lifecycle: spawn a PTY, stream it over a WebSocket, and wire
// the kitty/Shift+Enter and macOS editing key handling.

import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon } from "@xterm/addon-search";
import { SerializeAddon } from "@xterm/addon-serialize";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Terminal } from "@xterm/xterm";

import { api } from "./api";
import { macEditingSeq } from "./editing";
import { getFontSize } from "./font";
import { createKitty } from "./kitty";
import {
  activeWorkspace,
  getState,
  poll,
  refresh,
  type Session,
  sessions,
} from "./store";

const enc = new TextEncoder();

// xterm scrollback to capture (lines, not bytes). The server caps the
// on-disk size separately.
const SCROLLBACK_LINES = 5000;

function binStr(u8: Uint8Array): string {
  let s = "";
  for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
  return s;
}

function resumedSeparator(): string {
  // ISO-like local timestamp, trimmed to minutes.
  const now = new Date();
  const pad = (n: number): string => String(n).padStart(2, "0");
  const ts =
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  return `\r\n\x1b[2m──── session resumed @ ${ts} ────\x1b[0m\r\n`;
}

async function fetchScrollback(tid: string): Promise<string> {
  try {
    const r = await api(`/tabs/${tid}/scrollback`);
    if (!r.ok) return "";
    return await r.text();
  } catch {
    return "";
  }
}

function persistScrollback(tid: string, content: string): void {
  // keepalive lets the request outlive a page hide / unload.
  void fetch(`/api/tabs/${tid}/scrollback?t=${window.TERMINUX_TOKEN}`, {
    method: "PUT",
    headers: { "Content-Type": "text/plain" },
    body: content,
    keepalive: true,
  }).catch(() => {});
}

function discardScrollback(tid: string): void {
  void fetch(`/api/tabs/${tid}/scrollback?t=${window.TERMINUX_TOKEN}`, {
    method: "DELETE",
  }).catch(() => {});
}

export function disposeSession(tid: string): void {
  const s = sessions.get(tid);
  if (s) {
    s.ws.close();
    s.term.dispose();
    s.host.remove();
    sessions.delete(tid);
  }
}

async function openTerminal(tid: string, restore = true): Promise<void> {
  const host = document.createElement("div");
  host.className = "term-host";
  document.getElementById("terminals")?.appendChild(host);

  const term = new Terminal({
    fontFamily: "Menlo, Consolas, monospace",
    fontSize: getFontSize(),
    cursorBlink: true,
    theme: { background: "#1a1b26", foreground: "#c0caf5" },
  });
  const fit = new FitAddon();
  term.loadAddon(fit);
  const search = new SearchAddon();
  term.loadAddon(search);
  const serialize = new SerializeAddon();
  term.loadAddon(serialize);
  // URLs are highlighted on hover; require a modifier to open, matching
  // iTerm2 / Terminal.app conventions so a stray click can't navigate.
  // Routed through the backend because pywebview's WKWebView ignores JS
  // window.open() — the same handler then also works in --no-window mode.
  term.loadAddon(
    new WebLinksAddon((event, uri) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      void api("/open-url", {
        method: "POST",
        body: JSON.stringify({ url: uri }),
      });
    }),
  );

  // Per the SerializeAddon docs, replay BEFORE term.open: the parser fills
  // the buffer first, then rendering starts on a settled state — and the
  // separator lands on the shell's main buffer, not whatever alt-screen
  // mode the previous session might have been carrying.
  if (restore) {
    const saved = await fetchScrollback(tid);
    if (saved) {
      term.write(saved);
      term.write(resumedSeparator());
    }
  }

  term.open(host);
  fit.fit();

  const r = await api(`/tabs/${tid}/spawn`, {
    method: "POST",
    body: JSON.stringify({ cols: term.cols, rows: term.rows }),
  });
  const { terminal_id } = (await r.json()) as { terminal_id: string };

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/pty/${terminal_id}?t=${window.TERMINUX_TOKEN}`,
  );
  ws.binaryType = "arraybuffer";
  const kitty = createKitty();
  let kittyCarry = "";
  const sendInput = (s: string): void => {
    if (ws.readyState === 1) ws.send(enc.encode(s));
  };
  const sess: Session = {
    term,
    fit,
    search,
    serialize,
    ws,
    host,
    exited: false,
    dirty: false,
  };
  sessions.set(tid, sess);

  // Auto-copy on selection (iTerm2-style), gated by the persisted pref. We
  // read the pref live each time so a toggle takes effect immediately.
  term.onSelectionChange(() => {
    if (!getState()?.ui.copy_on_select) return;
    const sel = term.getSelection();
    if (sel) void navigator.clipboard?.writeText(sel);
  });

  // OSC 0/2 title from the shell tracks the tab name (unless pinned).
  let lastTitle = "";
  term.onTitleChange((t: string) => {
    const title = t.trim();
    if (!title || title === lastTitle) return;
    lastTitle = title;
    api(`/tabs/${tid}`, {
      method: "PATCH",
      body: JSON.stringify({ osc_title: title }),
    }).then(() => poll()); // render-only refresh, no focus steal
  });

  ws.onmessage = (ev: MessageEvent): void => {
    if (typeof ev.data === "string") {
      const msg = JSON.parse(ev.data) as { type: string; code?: number | null };
      if (msg.type === "exit") {
        const code = msg.code != null ? ` with code ${msg.code}` : "";
        sess.exited = true;
        term.write(
          `\r\n\x1b[2m[process exited${code} — press Enter to restart]\x1b[0m\r\n`,
        );
        void refresh();
      } else if (msg.type === "dropped") {
        term.write(
          "\r\n\x1b[2m[output dropped — terminal fell behind]\x1b[0m\r\n",
        );
      }
      return;
    }
    const u8 = new Uint8Array(ev.data as ArrayBuffer);
    kittyCarry = kitty.scan(kittyCarry + binStr(u8), sendInput);
    term.write(u8);
    sess.dirty = true;
  };
  ws.onopen = (): void => {
    fit.fit();
    ws.send(
      JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }),
    );
  };
  term.onData((d: string) => sendInput(d));
  term.onResize(({ cols, rows }: { cols: number; rows: number }) => {
    if (ws.readyState === 1)
      ws.send(JSON.stringify({ type: "resize", cols, rows }));
  });

  // macOS editing chords first (own every event type so the webview can't
  // act on them); then Shift+Enter / modified Enter as newline.
  term.attachCustomKeyEventHandler((e: KeyboardEvent): boolean => {
    if (sess.exited) {
      // The shell is gone; Enter relaunches it in the same tab.
      if (e.type === "keydown" && e.key === "Enter") {
        e.preventDefault();
        void restartTerminal(tid);
      }
      return false;
    }
    const edit = macEditingSeq(e);
    if (edit !== null) {
      if (e.type === "keydown") {
        e.preventDefault();
        sendInput(edit);
      }
      return false;
    }
    if (e.key !== "Enter") return true;
    const modified = e.shiftKey || e.altKey || e.ctrlKey || e.metaKey;
    if (!modified) return true; // plain Enter → xterm's default CR (submit)
    if (e.type !== "keydown") return false;
    const seq = kitty.encodeEnter(e) ?? (e.shiftKey ? "\n" : null);
    if (seq === null) return false;
    sendInput(seq);
    return false;
  });
}

async function restartTerminal(tid: string): Promise<void> {
  // Restart-in-place: previous shell exited, user pressed Enter. New shell,
  // new history — drop the captured buffer instead of replaying it.
  discardScrollback(tid);
  disposeSession(tid);
  await openTerminal(tid, false);
  const s = sessions.get(tid);
  if (s) {
    s.host.hidden = false;
    s.fit.fit();
    s.term.focus();
  }
}

function flushScrollback(force = false): void {
  if (!force && !getState()?.ui.scrollback_persist) return;
  for (const [tid, s] of sessions) {
    if (!force && !s.dirty) continue;
    // excludeAltBuffer: full-screen TUIs (Claude Code, vim, less, fzf, tmux)
    // own the alt buffer; the moment they exit the contents are gone, so
    // capturing them produces a replay that flips the next session into
    // alt-screen mode and dumps stale content on top of the new shell.
    // excludeModes: don't replay terminal modes (application keypad,
    // bracketed paste, etc.) that the previous session left set — the
    // fresh shell will reassert whatever it needs.
    const content = s.serialize.serialize({
      scrollback: SCROLLBACK_LINES,
      excludeAltBuffer: true,
      excludeModes: true,
    });
    persistScrollback(tid, content);
    s.dirty = false;
  }
}

// Periodic backstop (5s) plus a final flush on page hide. pywebview's close
// doesn't always fire beforeunload, so the interval is what we actually rely
// on; the hide handler just catches anything written in the last few seconds.
export function installScrollbackAutosave(): void {
  setInterval(() => flushScrollback(), 5000);
  const finalFlush = (): void => flushScrollback(true);
  window.addEventListener("pagehide", finalFlush);
  window.addEventListener("beforeunload", finalFlush);
}

export async function ensureActiveTerminal(): Promise<void> {
  const ws = activeWorkspace();
  const empty = document.getElementById("empty");
  if (!ws || !ws.active_tab_id) {
    if (empty) empty.style.display = "flex";
    for (const s of sessions.values()) s.host.hidden = true;
    return;
  }
  if (empty) empty.style.display = "none";
  const tid = ws.active_tab_id;
  for (const [id, s] of sessions) s.host.hidden = id !== tid;
  if (!sessions.has(tid)) await openTerminal(tid);
  const s = sessions.get(tid);
  if (s) {
    s.fit.fit();
    s.term.focus();
  }
}
