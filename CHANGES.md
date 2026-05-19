# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
