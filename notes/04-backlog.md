# Backlog

This is a snapshot of what's deferred, what's open, and what to pick up next, as of 0.11. It draws on `02-technical-spec.md` (§10–§14), `01-functional-spec.md` (§8–§9), `03-future-considerations.md`, `06-windows-port.md`, and the "on the roadmap" callouts in the public docs.

This is a working document: refresh it when items land or new ones surface.

## Big-ticket platform features

These are additive along existing interfaces. The backend already speaks HTTP + WebSocket, owns the PTYs, and persists structure separately from live processes; every item below sits on top of that without changing the shape.

- **Windows follow-ups**: terminals on Windows shipped in 0.10 (see [`06-windows-port.md`](06-windows-port.md)). Still open: a standalone Windows bundle (PyInstaller, `icon.ico`), a setting to pick the shell (Git Bash, MSYS2), and a Windows runner in CI.
- **Split panes**: each tab gets a pane tree; each leaf is just another `WS /pty/{tid}`. The persistence schema reserved the shape. The backend per-terminal model stays as is: a tab holds N terminals where it held 1 (technical-spec §12). The Preact islands (since 0.9.0) give the pane UI a component model to build on.
- **Real auth for the open web**: remote mode (`--server` / `--connect`, auto-reconnect) shipped, and web mode works with `--host`. Both rely on a single shared access code with per-IP lockout, which is fine on loopback or through an SSH tunnel. Exposing terminux directly on a network wants real, multi-user auth (technical-spec §6 note).

## UX surface area

- **Settings window.** Explicitly out of v1 (functional-spec §9). Today's prefs (auto-copy, scrollback persistence, font size, sidebar width) are toggled via shortcuts and the command palette.
- **Custom key bindings UI.** Shortcuts are hard-coded (functional-spec §8). A remap UI is deferred.
- **Unified command palette.** The "quick switcher + command launcher → one overlay" design lives in [`03-future-considerations.md`](03-future-considerations.md). We lean towards unifying; the blocker is mockups proving a mixed list reads cleanly. The UX bar is concrete (visual grouping, sensible default order, no `>` prefix mode).
- **New-workspace placement policy.** Make it configurable; v1 appends to the end (functional-spec §4.2).

## Open technical questions (technical-spec §14)

- **Eager vs lazy shell spawn on restore.** Today a restored tab respawns its shell on first view. Eager spawn would warm them up at startup; lazy keeps startup fast.
- **Backpressure thresholds + flush interval.** Still at the initial defaults (4 MiB / ~4 ms), never re-tuned against real workloads.
- **Cwd from the shell.** Parsing OSC 7 / OSC 9;9 would track a shell's directory without `libproc`/`lsof`, including inside SSH sessions. Windows needs it anyway (see `06-windows-port.md` §4).

## Hardening / loose ends

- **Test the cross-platform shortcuts on real machines** (0.11): `Ctrl+Shift+V` pasting natively in the macOS window (a `keyDown_` patch, tested only on a hidden window), and plain `Ctrl+C` / `Ctrl+V` on Linux.
- **Audit leftovers, deferred on purpose**: the 250 ms post-drag click guard in `reorder.ts` (the alternative depends on WebKit's click dispatch order); renaming `Workspace.has_unseen_output` to `is_ready` (changes the wire field); the one-line `setActive*Optimistic` wrappers in `store.ts`; replacing the `persist` flag of `AppController` with an injected data directory.
- **macOS code-signing / notarization** for the packaged `.app`. It's currently distributed unsigned. See `docs/src/developers/packaging.md`.
- **Per-Terminal async write queue.** The PTY master is non-blocking and `UnixPty.write` paces itself with `select()` on a worker thread, so the event loop is safe. A permanently stuck shell still parks one `to_thread` worker forever. The full fix queues writes in a small per-Terminal buffer, drains it via `loop.add_writer`, and drops on overflow with a one-shot notice (same shape as the subscriber output fan-out). See `05-lessons-learned.md`, "Server-side concurrency".

## Picking next

By impact-per-effort, ranked:

1. **Unified command palette.** Small surface, immediate UX win: mockups, then merge `palette.ts` and `cmdpalette.ts` (both are built on `createFuzzyOverlay`, itself on the shared `createOverlay`). It would also retire the last shortcut difference between platforms: `Cmd+P` is the quick switcher on macOS while `Ctrl+Shift+P` is the command palette everywhere.
2. **Split panes.** The biggest "feels like a real terminal" feature. The plumbing is pane-aware in the spec; the work is per-tab pane-tree state, a drag-to-split UI, and routing keystrokes to the focused pane.
3. **A Windows bundle and a shell setting.** Windows users currently need Python and uv; a standalone app and a choice of shell would remove the last rough edges.
4. **Real auth.** Mostly server-side; it opens remote mode to setups without an SSH tunnel.

The rest is small and opportunistic.
