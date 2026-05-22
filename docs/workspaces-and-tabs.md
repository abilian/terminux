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
- **Automatic naming.** A workspace's name tracks the **first tab's**
  working directory automatically — drag a different tab into slot 0 to
  promote it into the naming role; jumping between tabs within a workspace
  doesn't keep renaming it. An explicit rename *pins* the name so it stops
  tracking, and the pinned name survives across restarts. Inline rename
  works for both workspaces and tabs.
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

## Session activity

terminux tracks per-workspace **active time** for the current session — the
seconds you've actually been typing into one of its tabs. Counting rules:

- Credit goes to the **currently active workspace** at the moment of each
  1 Hz tick.
- A tick credits a second only if you've typed something in the last
  **30 seconds**. AFK time, long-running silent commands, and time spent
  in another app don't count.
- Counters are **in-memory only** — they reset when terminus exits.

Each workspace's accumulated time shows inline in the sidebar (small, dim,
right-aligned next to the name). Hover for the same value as a tooltip.

The **command palette** (`F1` on Linux — provisional — or `Cmd+Shift+P` on macOS) is a launcher — verbs only,
fuzzy-filtered. Commands relevant to activity stats:

- **Display usage stats** — opens a focused overlay listing every
  workspace ranked by active time, with a bar showing each one's share of
  the busiest. Escape or click outside to dismiss.
- **Reorder sidebar by activity (most used first)** — one-shot
  rearrangement of the sidebar; nothing keeps reordering automatically
  after that.
- **Reset session activity counters** — wipes all per-workspace
  accruals and restarts the session clock.

## Working vs ready

The sidebar status dot turns **amber** when a workspace has a foreground
task running and nothing more urgent applies — same color language as CI
dashboards (green = result for you, amber = wait, empty = nothing here).
Priority is **active > exited > unseen > busy > idle**: `unseen` (green)
already says "go check this," so it wins over `busy` (amber). The signal
sources, in order of preference:

1. **`OSC 133;C` / `;D`** when [shell integration](shell-integration.md) is
   set up — the shell itself tells terminux when a command begins and ends.
2. **`tcgetpgrp` on the PTY**, comparing the foreground process group to the
   shell's pid — works with no setup. Interactive TUIs (vim, less, fzf, …)
   register as "working" while focused; OSC 133 gives the more precise
   behavior if you want it.

State is recomputed each time the frontend polls `/api/state` (~every 2 s);
no separate poll task.

## Attention & activity

- Background tabs that produce output show an **activity indicator**.
- A tab that emits **BEL**, an **`OSC 9`** notification, or completes a
  long-running command (**`OSC 133;D`** — see [Shell
  integration](shell-integration.md)) while not in view raises an
  **attention badge** that propagates up to its workspace.
- The BEL byte that terminates an `OSC 0/2` *title* update doesn't count —
  tools like Claude Code change their title constantly while working.

## Persistence

terminux saves **structure** and the **visible buffer** — never live
processes.

What persists across restarts:

- Workspaces and their tabs (the layout).
- Window geometry, sidebar width and collapsed state, terminal font size —
  stored server-side so they survive the loopback port changing each run.
- Each shell's last working directory.
- **Each tab's scrollback** (last ~5000 lines), captured periodically and on
  shutdown. On restart it's replayed into a fresh terminal followed by a dim
  `──── session resumed @ <time> ────` separator, then the new shell starts
  underneath.

On restart, every tab respawns a **fresh shell** in the directory it was in at
exit. If that directory no longer exists, it falls back to the default. The
restored scrollback is **display-only** — it's text, not state: commands shown
above the separator are *not* still running.

!!! note "Privacy"
    Scrollback can contain secrets (tokens echoed by a CLI, `cat secret.env`,
    etc.). Files are stored locally only, capped at 2 MB per tab, and
    deleted when the tab or workspace is closed. To disable persistence
    entirely, set `scrollback_persist` to false via `PATCH /api/ui`.

!!! warning "Not persisted"
    Running processes are **not** restored — only their visible output.
    Split panes, client/server detach, and Windows PTY are still on the
    roadmap (see `notes/technical-spec.md` §11–§14).

!!! info "Full-screen TUIs (Claude Code, vim, less, tmux, fzf…)"
    Full-screen apps draw into the terminal's **alternate screen buffer**,
    which they own and clean up when they exit. By the time terminux saves a
    tab's view (and certainly by the time the app has been SIGHUP'd on quit),
    that buffer is gone — the OS gave it back to the program and the program
    gave it back to the system.

    What you'll see restored is the **shell session around** the TUI — your
    commands, their non-fullscreen output, and the shell prompt — not the
    TUI's own UI. This is the same limit iTerm2's session restoration hits;
    there's no faithful way around it.

## Input integrations

- **Drag a file** onto the terminal to insert its full, shell-quoted path.
- macOS line-editing chords and `Shift+Cmd`+arrow navigation are supported;
  `Shift+Enter` inserts a newline (works with Claude Code and similar tools).
- **Clickable URLs.** URLs in the terminal are highlighted on hover and open
  with `Ctrl+click` on Linux or `Cmd+click` on macOS — matching iTerm2 and
  Terminal.app, so a stray click
  never navigates.
- **Auto-copy on select** (iTerm2-style) is available as a persisted
  preference; off by default. Toggle with `Ctrl+Shift+Alt+C` (Linux) or
  `Cmd+Alt+C` (macOS) — see
  [Keyboard shortcuts](keyboard-shortcuts.md)).
