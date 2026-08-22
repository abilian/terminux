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
import { appMod } from "./platform";
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

interface SavedScrollback {
  content: string;
  // Dimensions the buffer was captured at — used to construct the fresh
  // xterm at the same size so the post-write fit() reflows cleanly.
  // Missing for legacy (pre-v2) saves; the caller falls back to defaults.
  cols?: number;
  rows?: number;
}

async function fetchScrollback(tid: string): Promise<SavedScrollback | null> {
  try {
    const r = await api(`/tabs/${tid}/scrollback`);
    if (!r.ok) return null;
    const body = await r.text();
    if (!body) return null;
    // v2 format: a one-line JSON header ({"v":2,"cols":…,"rows":…}\n) then
    // the raw ANSI. v1 saves had no header — fall through to legacy.
    if (body.charCodeAt(0) === 0x7b /* '{' */) {
      const nl = body.indexOf("\n");
      if (nl > 0) {
        try {
          const head = JSON.parse(body.slice(0, nl)) as {
            v?: number;
            cols?: number;
            rows?: number;
          };
          if (
            head.v === 2 &&
            typeof head.cols === "number" &&
            typeof head.rows === "number"
          ) {
            return {
              content: body.slice(nl + 1),
              cols: head.cols,
              rows: head.rows,
            };
          }
        } catch {
          /* malformed header — fall through */
        }
      }
    }
    // Pre-v2 (no header) or unrecognized: drop it. Replaying raw v1 bytes
    // into a default-sized xterm was the garble bug; the next save will
    // overwrite with a clean v2 envelope.
    discardScrollback(tid);
    return null;
  } catch {
    return null;
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
    s.disposed = true; // stops any in-flight reconnect loop
    s.ws?.close();
    s.term.dispose();
    s.host.remove();
    sessions.delete(tid);
  }
}

// Reconnect backoff bounds. Retry forever: the backend keeps a per-terminal
// backlog precisely so a re-attach can replay recent output, and remote
// mode's promise ("sleep the laptop, reconnect later") depends on it.
const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 5000;

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

function sendInput(sess: Session, data: string): void {
  const w = sess.ws;
  if (w && w.readyState === 1) w.send(enc.encode(data));
}

/**
 * Spawn (or re-acquire) the tab's PTY and attach a fresh WebSocket.
 *
 * Resolves "ok" once the socket is open, "gone" when the tab no longer
 * exists server-side, "fail" on any transient error (caller retries).
 * With `reset` the xterm buffer is cleared right before the server
 * replays its backlog, so a reconnect repaints instead of duplicating.
 */
async function connect(
  tid: string,
  sess: Session,
  reset: boolean,
): Promise<"ok" | "gone" | "fail"> {
  let terminalId: string;
  try {
    const r = await api(`/tabs/${tid}/spawn`, {
      method: "POST",
      body: JSON.stringify({ cols: sess.term.cols, rows: sess.term.rows }),
    });
    if (r.status === 404) return "gone";
    if (!r.ok) return "fail";
    terminalId = ((await r.json()) as { terminal_id: string }).terminal_id;
  } catch {
    return "fail";
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws: WebSocket;
  try {
    ws = new WebSocket(
      `${proto}://${location.host}/pty/${terminalId}?t=${window.TERMINUX_TOKEN}`,
    );
  } catch {
    // e.g. a CSP refusal throws synchronously (SecurityError) — retryable,
    // never fatal to the session.
    return "fail";
  }
  ws.binaryType = "arraybuffer";
  sess.ws = ws;

  let kittyCarry = "";
  ws.onmessage = (ev: MessageEvent): void => {
    if (typeof ev.data === "string") {
      const msg = JSON.parse(ev.data) as { type: string; code?: number | null };
      if (msg.type === "exit") {
        const code = msg.code != null ? ` with code ${msg.code}` : "";
        sess.exited = true;
        sess.term.write(
          `\r\n\x1b[2m[process exited${code} — press Enter to restart]\x1b[0m\r\n`,
        );
        void refresh();
      } else if (msg.type === "dropped") {
        sess.term.write(
          "\r\n\x1b[2m[output dropped — terminal fell behind]\x1b[0m\r\n",
        );
      }
      return;
    }
    const u8 = new Uint8Array(ev.data as ArrayBuffer);
    kittyCarry = sess.kitty.scan(kittyCarry + binStr(u8), (d) =>
      sendInput(sess, d),
    );
    sess.term.write(u8);
    sess.dirty = true;
  };

  const opened = await new Promise<boolean>((resolve) => {
    ws.onopen = (): void => resolve(true);
    ws.onclose = (): void => resolve(false); // refused before opening
  });
  if (!opened) return "fail";

  // From here on, a close means the connection was lost mid-flight.
  ws.onclose = (): void => {
    if (!sess.disposed && !sess.exited) void reconnectLoop(tid, sess);
  };
  if (reset) sess.term.reset(); // the replayed backlog repaints from scratch
  sess.fit.fit();
  ws.send(
    JSON.stringify({
      type: "resize",
      cols: sess.term.cols,
      rows: sess.term.rows,
    }),
  );
  return "ok";
}

async function reconnectLoop(tid: string, sess: Session): Promise<void> {
  if (sess.reconnecting) return;
  sess.reconnecting = true;
  sess.term.write("\r\n\x1b[2m[connection lost — reconnecting…]\x1b[0m\r\n");
  let backoff = RECONNECT_MIN_MS;
  while (!sess.disposed && !sess.exited) {
    await sleep(backoff);
    if (sess.disposed || sess.exited) break;
    const res = await connect(tid, sess, true);
    if (res === "ok") break;
    if (res === "gone") {
      // Tab deleted server-side while we were away; drop the local session
      // and let the next state refresh reconcile the UI.
      disposeSession(tid);
      void refresh();
      break;
    }
    backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
  }
  sess.reconnecting = false;
}

async function openTerminal(tid: string, restore = true): Promise<void> {
  const host = document.createElement("div");
  host.className = "term-host";
  document.getElementById("terminals")?.appendChild(host);

  // Fetch first so we can size the buffer to match the captured session.
  // Per SerializeAddon: write into a terminal of the same size and resize
  // after — otherwise the post-fit reflow garbles the layout (lines wrap
  // at xterm's default 80 cols then never un-wrap correctly).
  const saved = restore ? await fetchScrollback(tid) : null;

  const term = new Terminal({
    fontFamily: "Menlo, Consolas, monospace",
    fontSize: getFontSize(),
    cursorBlink: true,
    cols: saved?.cols,
    rows: saved?.rows,
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
      // Cmd+click on macOS, Ctrl+click on Linux — Ctrl+click on macOS is
      // the platform context-menu chord, deliberately left alone.
      if (!appMod(event)) return;
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
  //
  // term.write() is async — it queues bytes for the parser. We MUST wait
  // for the parser to consume the saved bytes at the captured size before
  // fit() resizes the buffer; otherwise the resize lands mid-parse and
  // wrapped rows that should hit the right edge and continue at col 0
  // instead bleed across into a cumulative staircase.
  if (saved) {
    await new Promise<void>((resolve) => {
      term.write(saved.content + resumedSeparator(), () => resolve());
    });
  }

  term.open(host);
  fit.fit();

  const sess: Session = {
    term,
    fit,
    search,
    serialize,
    ws: null,
    host,
    exited: false,
    disposed: false,
    reconnecting: false,
    kitty: createKitty(),
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

  term.onData((d: string) => sendInput(sess, d));
  term.onResize(({ cols, rows }: { cols: number; rows: number }) => {
    const w = sess.ws;
    if (w && w.readyState === 1)
      w.send(JSON.stringify({ type: "resize", cols, rows }));
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
        sendInput(sess, edit);
      }
      return false;
    }
    if (e.key !== "Enter") return true;
    const modified = e.shiftKey || e.altKey || e.ctrlKey || e.metaKey;
    if (!modified) return true; // plain Enter → xterm's default CR (submit)
    if (e.type !== "keydown") return false;
    const seq = sess.kitty.encodeEnter(e) ?? (e.shiftKey ? "\n" : null);
    if (seq === null) return false;
    sendInput(sess, seq);
    return false;
  });

  const res = await connect(tid, sess, false);
  if (res === "gone") {
    disposeSession(tid);
    return;
  }
  if (res === "fail") void reconnectLoop(tid, sess); // keep trying quietly
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
    // v2 envelope: a single JSON header line carrying the buffer's cols/rows
    // so the next launch can construct xterm at the original size and let
    // fit() reflow cleanly toward the new viewport.
    const header = JSON.stringify({
      v: 2,
      cols: s.term.cols,
      rows: s.term.rows,
    });
    persistScrollback(tid, `${header}\n${content}`);
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
