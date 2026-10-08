# Backlog

This is a snapshot of what's deferred, what's open, and what to pick up
next. Compiled from `technical-spec.md` (§10–§14),
`functional-spec.md` (§8–§9), `future-considerations.md`, and the
"on the roadmap" callouts in the public docs.

This is a working document: refresh it when items land or new ones surface.

## Big-ticket platform features

These are explicitly spec'd as additive along existing interfaces (no
rewrite). The backend already speaks HTTP + WebSocket, owns the PTYs,
and persists structure separately from live processes; every item below
sits on top of that without changing the shape.

- **Windows PTY**: put `pywinpty` (ConPTY) behind the existing
  `PtyBackend` Protocol. The default shell probe tries `pwsh` → `powershell` →
  `cmd`. Process-tree kill uses a Job Object. Land Unix first; Windows
  slots into the same interface as `UnixPty`. (technical-spec §10)
- **Split panes**: each tab gets a pane tree (terax's `PaneNode`); each leaf
  is just another `WS /pty/{tid}`. Persistence schema reserved the
  shape. The backend per-terminal model stays as is: a tab holds N terminals
  where it held 1 (technical-spec §12).
- **Frontend framework: Preact islands wait for split panes.**
  We decided on 2026-09-16 that the UI stays vanilla TS until split panes
  start or the next "background re-render wiped in-progress UI
  state" bug lands; then adopt **Preact** incrementally as islands
  (sidebar / tab bar / overlays), keeping `terminal.ts`, kitty, and
  keymap imperative. The rationale is that DOM diffing retires the
  `isEditing*` guard family, costs ~4 KB gzipped, and holds the
  Safari-14 WebKit floor. First trial lives on the `feat-preact`
  branch; add `@preact/signals` only if the islands multiply.
- **Client/server detach**: the backend already *is* a server owning
  the PTYs. Run it headless; let a UI connect over the same HTTP/WS
  protocol. Terminals keep running across UI restarts because the server process
  outlives the window. (technical-spec §12)
- **Web mode** basically works today via `--no-window`. The
  remaining bar is replacing the per-session token with real auth
  before anyone seriously binds beyond loopback. (technical-spec §6
  note)

## UX surface area

- **Settings window.** Explicitly out of v1 (functional-spec §9).
  Today's prefs (auto-copy, scrollback persistence, font size,
  sidebar width) are toggled via shortcuts and the command palette.
- **Custom key bindings UI.** Shortcuts are hard-coded
  (functional-spec §8). cmux ships a remap UI; we deferred.
- **Unified command palette.** The "quick switcher + command launcher
  → one overlay" design lives in `notes/future-considerations.md`.
  Leaning *unify*; the blocker is mockups proving a mixed-list reads
  cleanly. UX bar to clear is concrete (visual grouping, sensible
  default order, no `>` prefix mode).
- **New-workspace placement policy.** cmux makes it configurable;
  v1 appends to the end. (functional-spec §4.4)

## Open technical questions (technical-spec §14)

- **Eager vs lazy shell spawn on restore.** Today a restored tab
  respawns its shell on first view. Eager spawn would warm them up
  at startup; lazy keeps startup fast.
- **Backpressure thresholds + flush interval.** Currently at terax's
  defaults (4 MiB / ~4 ms). Never re-tuned against real workloads.

## Hardening / loose ends

- **Real auth for non-loopback binds.** Per-session token is good
  enough for `127.0.0.1`; web/container mode wants a real auth story.
- **macOS code-signing / notarization** for the packaged `.app`.
  Currently distributed unsigned. See `docs/src/developers/packaging.md`.
- **Non-blocking PTY writes (O_NONBLOCK + per-Terminal write queue).**
  `_pump_in` now offloads `term.write` via `asyncio.to_thread`, so the
  event loop is safe, but a permanently stuck shell still parks one
  worker thread forever. The architecturally correct fix is to set the PTY
  master to non-blocking, queue writes in a small bytearray per
  Terminal, drain via `loop.add_writer`, drop on overflow with a
  one-shot notice (same shape as the subscriber output fan-out). Then
  no thread can ever be stuck on a wedged shell. See
  `notes/05-lessons-learned.md` "Server-side concurrency".

## Picking next

By impact-per-effort, ranked:

1. **Unified command palette.** Small surface, immediate UX win.
   Mockups + small refactor of `palette.ts` + `cmdpalette.ts` into
   one. Drops the asymmetry between Linux (`F1`) and macOS
   (`Cmd+Shift+P`) for the command launcher.
2. **Split panes.** Biggest "feels like a real terminal" feature.
   All the plumbing is already pane-aware in the spec; the work is
   per-tab pane-tree state, a drag-to-split UI, and routing keystrokes
   to the focused pane.
3. **Windows PTY.** Opens terminux to a third of the audience. Self-contained
   behind `PtyBackend`; no UI touch.
4. **Client/server detach + real auth.** Mostly server-side; high
   payoff for power users (detach from window, reattach later).

The rest is small / opportunistic.
