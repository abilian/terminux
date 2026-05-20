# Workspaces & tabs

terminux is organized around two concepts: **workspaces** (the left sidebar) and
**tabs** (the terminals inside a workspace).

![The workspaces sidebar with two workspaces and a tabbed terminal](images/main-window.png){ loading=lazy }

## Workspaces

A workspace is a named group of terminal tabs. The sidebar holds a persistent,
reorderable list of them.

- **Create / rename / reorder / close.** Drag-and-drop reordering works even in
  pywebview's WKWebView (where HTML5 drag-and-drop does not), with live
  before/after drop feedback.
- **Automatic naming.** A workspace's name tracks the active shell's working
  directory automatically. An explicit rename *pins* the name so it stops
  tracking. Inline rename works for both workspaces and tabs.
- **Status dot.** Each workspace shows a lightweight status indicator.
- **Closing the last tab** of a workspace closes the *workspace* and activates
  another one — it does not quit the app.

## Tabs

Each tab is an interactive terminal backed by its own real PTY shell.

- **Titles** follow the shell's `OSC 0` / `OSC 2` escape sequences unless pinned
  by a manual rename.
- **New tabs** open in the working directory of the previously active shell.
- **Restart in place.** A tab whose shell has exited can be restarted without
  losing its slot.
- **Background tabs keep streaming.** Switching workspaces or tabs preserves all
  running sessions; output continues with no switch jank.

## Attention & activity

- Background tabs that produce output show an **activity indicator**.
- A tab that emits **BEL** or an **`OSC 9`** notification while not in view
  raises an **attention badge** that propagates up to its workspace, so you can
  see which project wants you even when you're elsewhere.

## Persistence

terminux saves **structure**, not live processes.

What persists across restarts:

- Workspaces and their tabs (the layout).
- Window geometry, sidebar width and collapsed state, terminal font size —
  stored server-side so they survive the loopback port changing each run.
- Each shell's last working directory.

On restart, every tab respawns a **fresh shell** in the directory it was in at
exit. If that directory no longer exists, it falls back to the default.

!!! warning "Not persisted"
    Running processes and terminal scrollback are **not** saved. State is
    written atomically and versioned. Scrollback persistence is on the roadmap —
    see the [FAQ](faq.md).

## Input integrations

- **Drag a file** onto the terminal to insert its full, shell-quoted path.
- macOS line-editing chords and `Shift+Cmd`+arrow navigation are supported;
  `Shift+Enter` inserts a newline (works with Claude Code and similar tools).
- **Clickable URLs.** URLs in the terminal are highlighted on hover and open
  with `Cmd/Ctrl+click` — matching iTerm2 and Terminal.app, so a stray click
  never navigates.
- **Auto-copy on select** (iTerm2-style) is available as a persisted
  preference; off by default. Toggle with `Cmd/Ctrl+Alt+C` (see
  [Keyboard shortcuts](keyboard-shortcuts.md)).
