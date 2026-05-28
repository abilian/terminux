# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-05-28

### Added

- **Native application menu.** File / View / Workspace / Help, mirroring what the keyboard chords already do — discoverable at a glance, no docs trip required. On macOS the menu lives in the global menu bar; on Linux it sits in the window frame. Help → Documentation opens the project URL in the OS default browser. The menu is just another input surface on top of a new shared command bus, so adding a chord, a command-palette entry, and a menu item is one registration each.
- **App icon.** Stylized `>_` prompt on a dark rounded square. Used by the packaged `.app` (Finder + dock) and by the Linux GTK/QT window/taskbar entry. When launched from the CLI (`uv run terminux`) on macOS, the dock icon is overridden at startup via `NSApplication.setApplicationIconImage_` so it no longer falls back to the generic Python rocket.

### Changed

- **Keymap and command palette refactored onto a shared command bus** (`frontend/src/commands.ts`). Same handlers run regardless of whether you used a keyboard chord, picked from the palette, or clicked a menu item — no more duplicated dispatch. No user-visible change to existing shortcuts.

### Internal

- `open_url_in_default_app` extracted from `terminux.server.asgi` to a dedicated `terminux.openurl` module; reused by the menu's Help link and the existing `/api/open-url` route.
- `terminux.constants` added for URL constants surfaced in multiple places (`DOCS_URL` for now).
- `terminux.server.asgi` (~580 LOC) split along its natural seams: `controller.py` (the `AppController` domain layer), `api.py` (HTTP/WebSocket handlers), `middleware.py` (CSP + hardening headers). `asgi.py` is now the slim composition root and re-exports `AppController` so existing imports keep working.
- New `src/terminux/assets/` directory ships `icon.svg` (source), `icon.png` (GTK/QT + macOS-dock raster), and `icon.icns` (multi-resolution macOS bundle icon). The PyInstaller spec now bundles the dir and points `BUNDLE(icon=...)` at the `.icns`.

## [0.6.3] - 2026-05-28

### Fixed

- Inline workspace and tab renames no longer get overwritten by the 2 s status poll — each panel skips its re-render while an edit is in progress, and the input survives until you press Enter (commit) or Escape (cancel).

## [0.6.2] - 2026-05-27

### Changed

- **Sidebar bell badge removed.** The 🔔 icon is gone; the sidebar dot is the single visual indicator now. Green ("ready") fires only on the strict task-finished sources: raw `BEL` outside any OSC, `OSC 9`, `OSC 133;D` (≥ 2 s), or a new kernel-level `busy → idle` transition where busy was sustained for ≥ ~5 s. The kernel-level transition (driven by the existing 1 Hz ticker) covers shells without shell-integration — Claude Code returning to its prompt, `sleep 10` ending, `make test` finishing — so they all surface the same way. Plain output no longer flips a workspace to ready.

### Fixed

- Post-visit grace window suppresses both the busy promotion and the unseen flag for a few seconds after you leave a workspace, so the visit-redraw tail and xterm settling effects don't paint the dot the moment you look away. Previously the unseen flag was guarded but the busy promotion still ran, briefly flashing the dot amber.
- Frontend optimistic switch helpers now follow each activation PATCH with an immediate `poll()` instead of duplicating the backend's dwell-clearing logic on the client. Kills a "bell briefly reappears, then disappears" flicker without splitting state ownership.

## [0.6.1] - 2026-05-26

### Changed

- **Workspace name now tracks the *first* tab's working directory**, not the active tab's. Switching between tabs inside a workspace no longer keeps renaming it; drag a different tab into slot 0 to promote it into the naming role.

### Fixed

- **Sidebar dot stuck amber on idle workspaces.** `is_busy()` now requires recent PTY output (≤ 3 s) in addition to the existing kernel/`OSC 133` signals, so a TUI parked at its prompt (Claude Code waiting for input, idle vim, less) and a shell that emits `OSC 133;C` without the matching `;D` both release the amber dot once they go silent. Tradeoff: a fully silent long-running command briefly reads as idle until it emits again.
- **Sidebar dot green on a thinking Claude Code.** Spinner output kept flipping the dot to `unseen` (green) while the task was still working. Swapped the priority — `busy` now outranks `unseen` (new order: active > exited > busy > unseen > idle).
- **Rapid `Cmd+Shift+Arrow` switching could jump back to a previous workspace.** Two distinct races: a `GET /api/state` poll in flight at the time of the optimistic switch came back with the stale active id and wholesale-replaced the local state, and two fire-and-forget PATCHes could be applied out of user-issued order by the backend threadpool. Optimistic switch helpers now serialize their PATCHes through a shared promise queue, and polls reconcile against a per-id "expected" map until the backend confirms it has caught up.

### Internal

- `ci(ubuntu)` switched to `playwright install --with-deps chromium` — no more hand-maintained `libxcb-*` / `libxrandr` apt list to drift on every Playwright bump, and the suite stops downloading firefox/webkit/ffmpeg (~220 MB).
- Alpine CI dropped — Playwright doesn't officially support musl, the lint task wasn't pulling its weight.
- Dependency lockfile refresh.

## [0.6.0] - 2026-05-22

### Added

- Per-workspace **active-time tracking** for the current session, with an inline column in the sidebar, a dedicated stats overlay, and a command palette (`Cmd+Shift+P` on macOS, `F1` on Linux) exposing "Display usage stats", "Reorder sidebar by activity", "Reset session activity counters", and toggles for auto-copy-on-select and scrollback persistence.
- Amber **"busy" dot** in the sidebar when a workspace has a foreground task running. Prefers shell-integration signals (`OSC 133;C` / `;D`) when available, falls back to comparing `tcgetpgrp` with the shell's pid. Priority: active > exited > unseen > busy > idle.
- **Scrollback persistence**: each tab's last ~5000 lines are captured periodically and on shutdown, then replayed into the fresh shell on restart with a dim "session resumed @ <time>" separator. Capped at 2 MB per tab, dropped on deliberate close, can be disabled via the `scrollback_persist` UI pref.
- **Numbered workspace slots** in the sidebar (1-9) surface the matching jump shortcut.
- **Clickable URLs**: `Cmd`-click (macOS) or `Ctrl`-click (Linux) opens URLs in the OS default browser via a scheme-whitelisted backend opener (works around pywebview's WKWebView ignoring `window.open()`).
- **Auto-copy on selection** (iTerm2-style), off by default, persisted as a UI pref, toggleable via the command palette.
- **Quit confirmation** so an accidental `Cmd+Q` / `Ctrl+Q` doesn't drop live shells.
- **Shell-integration snippets** for bash / zsh / fish (`OSC 133;A/B/C/D`), gated on `TERM_PROGRAM=terminux`. See `docs/shell-integration.md`.
- **macOS TCC troubleshooting** section in `docs/packaging.md` for the lazy per-responsible-process permission model.

### Changed

- Linux keymap now uses `Ctrl+Shift+<key>` for app shortcuts (matching GNOME Terminal / Konsole / Alacritty), reserving plain `Ctrl+<key>` for the shell. macOS keeps `Cmd+<key>`. Workspace jump is `Ctrl+Shift+1..9` on Linux for consistency with the rest of the chord set.
- Docs and the launch blog post reframed as **Linux first, macOS second**.
- Attention scanner is now OSC-aware: a BEL inside `OSC 0/2` (title) doesn't count; only standalone BEL, `OSC 9`, or a long-enough `OSC 133;D` raise a badge. Renamed the "running" sidebar status to `unseen` for clarity.

### Fixed

- **Restart scrollback no longer garbles** — capture excludes the alt buffer, the v2 envelope carries the capture dimensions, the replay awaits the parser before fit, and the on-disk file is read in binary mode (`Path.read_text` was stripping `\r\n` → `\n`).
- **Concurrent route handlers no longer race** on `AppState`. Starlette's threadpool could land two sync handlers on `state.tabs` at the same time, triggering `RuntimeError: dictionary changed size during iteration` and silent state corruption. A reentrant lock now serializes all state read/write paths.
- **macOS press-and-hold disabled** so `hjkl` key-repeat works in vim / less / fzf.
- **Stats overlay closes on Escape** (capture-phase keydown so the xterm textarea doesn't swallow it).
- **Tab bar overflow**: tabs cap at ~18em wide and shrink to ~5em min before clipping; the trailing `+` button stays visible.
- **Cross-platform modifier confusion**: macOS no longer mis-fires `Ctrl+P` / `Ctrl+B` as app chords. Uses `e.code` (layout-independent) throughout.

### Performance

- **Workspace / tab switches feel instant.** Click handlers now mutate local state and re-render in the same frame, then fire the PATCH as fire-and-forget instead of awaiting `PATCH` + `GET /state` before re-rendering. The 2 s status poll heals any drift.

## [0.5.0] - 2026-05-19

First public preview. terminux is a cross-platform desktop terminal organized around a Workspaces sidebar and tabbed terminals, inspired by cmux but with a different architecture.

### Workspaces and tabs

- Workspaces sidebar with multiple tabbed terminal sessions per workspace.
- Workspace names track the active shell's working directory automatically; an explicit rename pins the name. Inline rename for both workspaces and tabs.
- Tab titles follow the shell's OSC 0/2 escape sequences unless pinned by a manual rename.
- New tabs open in the working directory of the previously active shell.
- Closing the last tab of a workspace closes the workspace and activates another, rather than quitting the app.
- An exited tab can be restarted in place.
- Drag-and-drop reordering of workspaces and tabs, with live before/after drop feedback (works in pywebview's WKWebView, where HTML5 drag-and-drop does not).

### Navigation and shortcuts

- `Cmd/Ctrl+1..9` to jump to a workspace, `Cmd/Ctrl+T` new tab, `Cmd/Ctrl+N` new workspace, `Cmd/Ctrl+W` close tab/workspace.
- `Cmd/Ctrl+Shift+[` / `Cmd/Ctrl+Shift+]` to move between tabs.
- `Cmd/Ctrl+P` quick switcher for workspaces and tabs (fuzzy match).
- `Cmd/Ctrl+F` find-in-terminal.
- `Cmd/Ctrl+B` toggles the sidebar.
- `Cmd/Ctrl+ +/-` to zoom the terminal font.
- macOS line-editing chords and `Shift+Cmd`+arrows navigation; `Shift+Enter` inserts a newline (works with Claude Code and similar tools).
- Shortcuts keep working while the terminal has focus.

### Attention and activity

- Background tabs that produce output show an activity indicator.
- A tab that emits BEL or an OSC 9 notification while not in view raises an attention badge that propagates to its workspace.

### Persistence

- Window geometry, sidebar width and collapsed state, and terminal font size persist across launches (stored server-side so they survive the loopback port changing each run).
- Each shell's working directory is remembered; on restart every tab respawns its shell in the directory it was in at exit. A directory that no longer exists falls back to the default.

### Input and integration

- Drag a file onto the terminal to insert its full, shell-quoted path.

### Architecture

- Python backend: a loopback Starlette/uvicorn ASGI server with a per-terminal WebSocket and ptyprocess-backed PTYs, hosted in a pywebview window. Also runnable in a browser via `--host`.
- TypeScript/Vite frontend built on xterm.js.
- Output backpressure: bounded per-subscriber buffer with coalesced flushing and an explicit drop notice; serialized PTY spawning.
- Hardened HTTP responses (CSP and security headers) and a per-session auth token.
- State is persisted atomically and versioned; only structure is saved — live processes and scrollback are not.

### Packaging

- macOS `.app` bundle and a Linux bundle. Windows is deferred.

### Tooling

- Test suite across unit, integration, and Playwright end-to-end tiers, plus vitest for the frontend.
- `make format` covers Python and the TypeScript sources; `make test` exercises the frontend tests as well.
