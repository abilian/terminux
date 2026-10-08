# Functional Specification: terminux v1

**Status:** Historical v1 design baseline. The app has shipped features beyond what's described here (native menu, scrollback persistence, per-workspace activity tracking, the "ready" dot, …); current behaviour lives in [`docs/`](../docs/) and [`CHANGES.md`](../CHANGES.md). This doc is kept as the record of original v1 scope and decisions.

Scope and intent come from [`vision.md`](vision.md); UX references from [`OLD/cmux-features.md`](OLD/cmux-features.md) and [`OLD/terax-features.md`](OLD/terax-features.md). This document defines *what the app does* from the user's point of view; [`technical-spec.md`](technical-spec.md) describes the technical design.

## 1. Product summary

terminux is a cross-platform desktop terminal application. The window has two regions: a **Workspaces** sidebar on the left and a **terminal area** on the right. Each workspace holds one or more **tabs**; each tab is a live interactive terminal. Workspaces and their tabs persist across restarts.

v1 ships the smallest thing that works well, on purpose. Reliability is the priority: the rebuild exists because cmux is buggy.

## 2. Primary concepts

- **Workspace**: a named container for a set of terminal tabs. Appears as a row in the left sidebar. Has a name and a status indicator. Persisted.
- **Tab**: one interactive terminal session inside a workspace. Has a title and belongs to exactly one workspace. Persisted (identity + metadata; see §7 for scrollback).
- **Terminal**: the running shell/PTY behind a tab and its on-screen rendering.
- **Active workspace / active tab**: exactly one of each is focused at any time; that terminal receives keyboard input.

v1 leaves out a "description" field on workspaces, split panes, an embedded browser, a file tree, AI, and git. (Splits, client/server, and web mode are explicit *future* items; see §11.)

## 3. Window & layout

```
┌───────────────┬─────────────────────────────────────────┐
│ WORKSPACES    │  [ tab1 ][ tab2 ][ tab3 ]    [ + ]      │  ← tab bar
│               ├─────────────────────────────────────────┤
│ ● project-a   │                                         │
│   project-b   │                                         │
│ ▸ scratch     │            terminal viewport            │
│               │                                         │
│               │                                         │
│ [ + New ]     │                                         │
└───────────────┴─────────────────────────────────────────┘
```

- The sidebar is vertically resizable-width (drag the divider) with a sensible min/default; width is persisted. The sidebar can be collapsed/expanded with a shortcut and a toggle control; collapsed state is persisted.
- The tab bar shows the active workspace's tabs left-to-right, plus a "new tab" (`+`) affordance.
- The terminal viewport fills the remaining area and reflows the PTY on resize.
- A single application window in v1 (no multi-window; cmux's multi-window is out of scope).
- Window size/position/maximized state persist across restarts.

## 4. Workspaces sidebar

### 4.1 Display

Each row shows:
- **Status indicator** (small leading dot/icon; see §4.4).
- **Name** (single line, ellipsized if long).
- An unobtrusive affordance on hover/selection for the row context menu.

The active workspace row is visually highlighted. No branch/PR/cwd/ports/notification metadata (that was cmux's agent-oriented surface; out of scope).

### 4.2 Operations

| Action | Trigger |
|---|---|
| Create workspace | "+ New" button; `Cmd/Ctrl+Shift+N` |
| Select / switch workspace | Click row; `Cmd/Ctrl+1..9` selects by position |
| Rename workspace | Double-click name, or context menu → Rename (inline edit, Enter commits, Esc cancels) |
| Reorder workspace | Drag row up/down |
| Close workspace | Context menu → Close; `Cmd/Ctrl+Shift+W` closes the active workspace |

- **New workspace** is created with one default tab running the user's default shell, and is selected immediately. Default name: `workspace N` (first integer not already in use); the user can rename it.
- **Closing a workspace** with running terminals prompts for confirmation ("Close workspace 'X'? N running terminal(s) will be terminated."). On confirm, all its terminals are terminated and the workspace is removed from persistence. Closing the last workspace immediately creates a fresh empty one (the app always has ≥1 workspace).
- New-workspace placement: appended to the end of the list in v1 (cmux's configurable placement policy is deferred).

### 4.3 Selection behavior

Switching workspaces preserves the previous workspace's running terminals (they keep running in the background) and restores its previously active tab. Navigation never kills a terminal; only an explicit tab/workspace close or a shell exit does.

### 4.4 Workspace status

Status is a small, automatically-derived indicator (no manual setting in v1):

| Status | Meaning | Visual |
|---|---|---|
| **Active** | This is the currently selected workspace | filled dot, accent color |
| **Running** | A non-selected workspace where ≥1 terminal produced output since it was last viewed | filled dot, neutral "activity" color |
| **Idle** | A non-selected workspace with no unseen activity | hollow/dim dot |
| **Exited** | All tabs' shells have exited (workspace has no live terminal) | dim dot with a small ✕ / distinct treatment |

"Unseen activity" resets when the workspace becomes active. This is intentionally simpler than cmux's notification system: v1 has neither OSC notifications, sounds, badges, nor hooks. (Status state machine refinements can follow in implementation.)

## 5. Tabs

### 5.1 Display

The tab bar shows each tab's title. The active tab is highlighted. Each tab has a close (`✕`) affordance (on hover/active). Tabs that have unseen output while not active show a subtle activity marker (dot). Overflowing tabs scroll horizontally (no dropdown in v1).

### 5.2 Operations

| Action | Trigger |
|---|---|
| New tab | `+` button; `Cmd/Ctrl+T` |
| Switch tab | Click; `Cmd/Ctrl+Shift+[` / `]` (prev/next); `Ctrl+Tab` / `Ctrl+Shift+Tab` |
| Close tab | `✕`; `Cmd/Ctrl+W` |
| Rename tab title | Double-click title (inline edit) |
| Reorder tabs | Drag within the tab bar |

- **New tab** spawns the default shell in the workspace's working directory rule (v1: the user's home directory, or the directory the app was launched from, see technical spec; per-workspace cwd memory is a possible later refinement).
- **Tab title** defaults to the shell/command name and updates from the terminal's title escape sequence (OSC 0/2) if emitted; a user-set title sticks (is not overwritten by OSC).
- **Closing a tab** terminates its terminal (SIGHUP/SIGTERM then SIGKILL escalation). Closing the last tab in a workspace leaves the workspace with zero tabs and shows an empty state with a prominent "New tab" affordance (the workspace is *not* auto-closed).
- When a shell **exits on its own**, the tab remains, showing the terminal's final output plus a dim "[process exited with code N — press Enter to close, or ⏎ to restart]"-style affordance (exact wording TBD in implementation). The user can close or relaunch. Tabs are never silently removed.

## 6. Terminal behavior

- Full interactive terminal: VT100/ANSI, 256/true color, mouse reporting, bracketed paste, UTF-8, resize/reflow.
- Rendered with a mature web terminal component (xterm.js) inside the webview.
- **Background tabs keep running and keep streaming.** Switching tabs/workspaces never pauses or tears down a PTY; output produced while a tab is hidden is buffered and present when the tab is shown again (terax's "dormant" behavior). No cold-start jank on switch.
- Keyboard input goes only to the active tab's terminal. Standard copy/paste: selection copy, `Cmd/Ctrl+Shift+C` / `Cmd/Ctrl+Shift+V` (platform-appropriate; right-click paste optional).
- Scrollback buffer with a bounded size (default e.g. 5,000 lines, configurable later). Mouse wheel / `Shift+PgUp`/`PgDn` scroll; any input jumps to bottom.
- Find-in-terminal: `Cmd/Ctrl+F` opens an inline search over the visible scrollback (basic substring; nice-to-have, may slip).
- Font family/size from a sane cross-platform default; zoom in/out (`Cmd/Ctrl + =` / `-`, reset `Cmd/Ctrl+0`), persisted.

## 7. Persistence

Persisted across restarts (local-only and file-based, with neither account nor telemetry):

- Workspace list: id, name, order.
- Per workspace: its tabs (id, title, order), which tab was active, which workspace was active.
- Window geometry, sidebar width, sidebar collapsed state, font zoom.

Not persisted in v1: live shell processes (terminals end with the app; a restored tab starts a fresh shell), and full scrollback history. Restored tabs open a new shell; the prior session's scrollback is not replayed. (Scrollback persistence and process re-attach are explicit non-goals for v1; the client/server direction enables re-attach later; see §11 and technical spec.)

On launch: restore the workspace/tab structure and re-spawn shells for the tabs of the **active** workspace eagerly; other workspaces' shells spawn lazily on first selection (keeps startup fast). The eager-vs-lazy split may be tuned during implementation.

If no persisted state exists or it fails to load (corruption, empty file), the app starts with a single workspace containing one tab; it never crashes on bad state, it logs and falls back.

## 8. Keyboard shortcuts (summary)

Modifier is `Cmd` on macOS, `Ctrl` on Linux/Windows.

| Shortcut | Action |
|---|---|
| `Mod+T` | New tab |
| `Mod+W` | Close tab |
| `Mod+Shift+N` | New workspace |
| `Mod+Shift+W` | Close workspace |
| `Mod+1..9` | Select workspace by position |
| `Mod+Shift+[` / `]` | Previous / next tab |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Cycle tabs |
| `Mod+B` | Toggle sidebar |
| `Mod+F` | Find in terminal |
| `Mod+=` / `Mod+-` / `Mod+0` | Font zoom in / out / reset |
| `Mod+Shift+C` / `Mod+Shift+V` | Copy / paste |

Shortcuts are fixed in v1 (no remap UI; cmux's customizable keymap is deferred). Shortcuts must not shadow common in-terminal control keys (e.g., plain `Ctrl+C`, `Ctrl+D`, `Ctrl+L` always reach the shell).

## 9. Settings (v1 scope)

v1 has no settings *window*. The few adjustable values (font zoom, sidebar width/collapsed) are changed via shortcuts/drag and persisted automatically. A real settings surface is deferred.

## 10. Non-functional expectations

- **Reliability first:** no lost input, no zombie processes, clean shutdown terminates all child shells, robust against malformed persisted state.
- **Responsiveness:** typing latency comparable to a native terminal; smooth output under high-throughput (e.g., `yes`, large build logs) without freezing the UI or unbounded memory growth (backpressure/drop with a visible notice, like terax).
- **Cross-platform:** macOS first; Linux and Windows targeted (Windows shell support may be staged; see technical spec).
- **Startup:** window visible and interactive quickly; lazy shell spawn for non-active workspaces.
- **No network** in v1 except the loopback transport between the webview and the local backend (see technical spec); nothing leaves the machine.

## 11. Explicitly out of scope for v1 (possible later)

v1 designs around these without building them; the architecture must not foreclose them:

- **Split panes** within a tab (tmux/zellij-style). Data model should leave room for a per-tab pane tree later (terax's `PaneNode` is the reference).
- **Client/server mode**: a detachable backend, so terminals outlive a UI restart and can be driven remotely. The chosen transport (local WebSocket) is forward-compatible.
- **Web mode**: serving the same UI to a normal browser. Also enabled cheaply by the chosen transport.
- Scrollback persistence / session replay, multi-window, settings UI, themes, keymap customization, notifications/hooks, agent integrations, remote SSH daemon, file navigator, embedded browser.

## 12. Open questions (resolve during implementation)

1. Exact workspace status state machine + "unseen activity" reset rules.
2. Exited-shell tab affordance wording and restart behavior.
3. Default working directory per new tab/workspace (home vs. launch dir vs. inherit).
4. Eager vs. lazy shell spawn tuning on restore.
5. Find-in-terminal: ship in v1 or defer.
6. Windows shell strategy timing (see technical spec).
