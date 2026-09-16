# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- "Reorder by activity" is now called "Sort by activity" in the menu and command palette, so it can't be confused with drag-and-drop reordering.

## [0.8.1] - 2026-08-30

### Added

- **You can always see which workspace you're in.** With the sidebar hidden (`Cmd/Ctrl+B`), the active workspace's status dot, number, and name now appear as a chip at the left of the tab bar; clicking it brings the sidebar back. The window and browser-tab title also carry the workspace name, so the answer to "where am I?" survives even minimizing the app.

## [0.8.0] - 2026-08-30

### Added

- **Terminals now reconnect automatically.** A lost connection — a backend stall, a network blip, a laptop waking from sleep — used to leave tabs permanently dead even though the shells were fine; the only cure was reopening the app. Each terminal now shows "[connection lost — reconnecting…]", redials with backoff until the server answers, and repaints from the server's output buffer. This is what makes remote mode's "disconnect and come back later" actually hold.
- **`--debug` now also opens the door to frontend debugging** in the desktop window: right-click → Inspect Element brings up the web inspector.

### Fixed

- **Web/remote mode: the page no longer reveals the access code.** Fetching the app's address without a valid code used to return the page with the code embedded in it — anyone who could reach the port could let themselves in. Every route now requires the code; your own links (which always carry it) are unaffected.
- **A stale browser tab can no longer lock you out.** Requests with an outdated code from your own machine could trip the brute-force guard and block the real window for a minute at a time. Local connections are now exempt from the lockout, which still protects servers exposed to a network.
- **Terminals open again on older Macs.** Two stacked problems broke every shell on e.g. Big Sur while the rest of the UI worked: a dependency upgrade had raised the frontend's minimum browser requirement past the WebKit that older macOS versions ship, and the security policy only declared `connect-src 'self'`, which older engines refuse to apply to websockets — so even a working terminal couldn't attach its data stream. The terminal library is pinned back to its proven line, the build explicitly targets Safari-14-era WebKit, and the policy now names the websocket origin explicitly. Applies wherever an older engine renders the UI: the desktop app, a `--connect` client, or a browser.
- **Hyperlinks printed by programs now open.** Clicking a link a program emitted as a real terminal hyperlink (Claude Code's artifact URLs, `ls --hyperlink`, modern CLI tools) used to show a browser warning popup whose OK button then did nothing. Such links now behave exactly like plain-text URLs: Cmd+click (macOS) / Ctrl+click (Linux) opens them in your default browser, with no popup; only `http`, `https`, and `mailto` links are ever opened.
- **Starting on a port that's already in use now fails with a clear error** instead of hanging forever with no output.
- **Access codes no longer appear in request logs** when running with `--debug` or `--trace`.

### Internal

- The controller never holds its state lock across a disk write, and new shells are forked off the event loop — closing the remaining freeze vectors found in a full audit. For anyone stuck on an older build, `notes/05-lessons-learned.md` documents how to unfreeze a live server without killing it.

## [0.7.2] - 2026-07-29

### Added

- **Remote access.** Run terminux on one machine and use it from another. Start `terminux --server` on the host and `terminux --connect <url>` on your laptop: you get the normal desktop window, but every shell lives on the server — long-running builds keep going while you close the lid, change networks, or switch devices. Access is protected by a short persistent code (`abc-def-ghi` style, rate-limited against guessing); the recommended setup keeps the server private behind an SSH port-forward. Dragging files into a remote window pastes their paths, same as locally. Full guide: `docs/src/remote.md`.

### Fixed

- **Pasting can no longer freeze the app.** Pasting a large block of text into a program that wasn't reading input (an editor mid-redraw, a stopped pager, a busy REPL) could freeze *every* terminal and the whole UI, sometimes permanently. Now at most the terminal you pasted into waits; everything else stays live.
- **Rare freeze of all terminals while idle.** A timing edge in how terminal output was read could lock up the whole app even with no user action. This class of freeze is now structurally impossible: reading terminal output can no longer stall the server.
- **Very large pastes could be silently truncated.** The tail of a paste could be dropped when the terminal accepted it in chunks; every byte is now delivered.

### Internal

- Terminal I/O is now non-blocking end to end.

## [0.7.1] - 2026-06-03

### Fixed

- **A failing external or network drive could permanently freeze the app (macOS).** When a mounted volume stopped responding, every terminal stopped accepting keystrokes and no new tabs could be opened (switching tabs still worked). The directory lookup that triggered it now uses a kernel call that cannot hang, and slow disk saves can no longer stall the terminals either.

### Added

- **The app now diagnoses its own stalls.** If the server stops responding for more than ~3 seconds, it automatically logs a warning with a snapshot of what it was doing at the time — so a freeze report comes with evidence attached. You can request the same snapshot at any moment with `kill -INFO <pid>` (macOS) or `kill -USR1 <pid>` (Linux), and disk operations that turn suspiciously slow are flagged in the log before they escalate into a freeze.
- **`--debug` and `--trace` flags** for verbose logging when investigating or reporting a problem. See `docs/src/developing.md#debugging-knobs`.

## [0.7.0] - 2026-05-28

### Added

- **Native application menu.** File / View / Workspace / Help — everything the keyboard shortcuts can do, now discoverable at a glance. On macOS it lives in the global menu bar, on Linux in the window frame. Menu items, keyboard shortcuts, and the command palette all trigger the same actions, so they can't drift apart. Help → Documentation opens the docs in your default browser.
- **App icon.** A stylized `>_` prompt on a dark rounded square — in the Finder and dock on macOS, the window/taskbar on Linux. Launching from the CLI on macOS no longer shows the generic Python rocket in the dock.

## [0.6.3] - 2026-05-28

### Fixed

- Renaming a workspace or tab is no longer interrupted by the background refresh — the edit stays open until you press Enter (save) or Escape (cancel).

## [0.6.2] - 2026-05-27

### Changed

- **One attention indicator instead of two.** The sidebar 🔔 bell badge is gone; the colored dot is now the single signal. The dot turns green ("ready") only when a task actually finishes — a command ending, a build completing, an interactive tool returning to its prompt — and this works with or without shell integration. Mere output no longer marks a workspace as ready.

### Fixed

- The dot no longer flashes in the first few seconds after you switch away from a workspace.
- Fixed a flicker where the ready indicator could briefly reappear right after you visited a workspace.

## [0.6.1] - 2026-05-26

### Changed

- **Workspace names follow the first tab's directory**, not the active tab's. Switching between tabs no longer keeps renaming the workspace; drag a different tab into the first slot to hand it the naming role.

### Fixed

- **Idle programs no longer keep the busy dot amber.** A tool sitting at its prompt (vim, less, Claude Code waiting for input) now releases the dot once it goes quiet. Tradeoff: a long-running command that prints nothing may briefly read as idle until it produces output again.
- **A still-working task no longer shows as ready.** Spinner-style output kept turning the dot green while the task was running; busy now takes precedence.
- **Rapid workspace switching no longer misfires.** Holding `Cmd+Shift+Arrow` could occasionally jump you back to a workspace you had already left.

## [0.6.0] - 2026-05-22

### Added

- Per-workspace **active-time tracking** for the current session, with an inline column in the sidebar, a dedicated stats overlay, and a command palette (`Cmd+Shift+P` on macOS, `F1` on Linux) exposing "Display usage stats", "Reorder sidebar by activity", "Reset session activity counters", and toggles for auto-copy-on-select and scrollback persistence.
- Amber **"busy" dot** in the sidebar when a workspace has a foreground task running — using shell-integration signals when available, otherwise by watching the shell's foreground process.
- **Scrollback persistence**: each tab's last ~5000 lines are saved and replayed into the fresh shell after a restart, under a dim "session resumed @ <time>" separator. Capped at 2 MB per tab, dropped when you deliberately close a tab, and can be turned off from the command palette.
- **Numbered workspace slots** in the sidebar (1-9) surface the matching jump shortcut.
- **Clickable URLs**: `Cmd`-click (macOS) or `Ctrl`-click (Linux) opens links in your default browser.
- **Auto-copy on selection** (iTerm2-style), off by default, toggleable from the command palette.
- **Quit confirmation** so an accidental `Cmd+Q` / `Ctrl+Q` doesn't drop live shells.
- **Shell-integration snippets** for bash / zsh / fish, for more precise busy/ready detection. See `docs/src/shell-integration.md`.
- **macOS permission (TCC) troubleshooting** section in `docs/src/packaging.md`.

### Changed

- Linux app shortcuts now use `Ctrl+Shift+<key>` (matching GNOME Terminal, Konsole, and Alacritty), leaving plain `Ctrl+<key>` for the shell; workspace jumps are `Ctrl+Shift+1..9`. macOS keeps `Cmd+<key>`.
- Docs and the launch blog post reframed as **Linux first, macOS second**.
- Shell title updates no longer raise the attention badge; only a real bell, a desktop-style notification, or a finished command does.

### Fixed

- **Restored scrollback no longer comes back garbled** after a restart.
- **Fixed a race that could corrupt workspace/tab state** when two actions landed at the same moment.
- **Holding a key now repeats it** in vim / less / fzf on macOS (press-and-hold accent popup disabled inside the terminal).
- **The stats overlay closes on Escape.**
- **Tab bar overflow**: tabs shrink gracefully as more open, and the `+` button stays visible.
- **macOS no longer mis-fires `Ctrl+P` / `Ctrl+B` as app shortcuts** — they reach the shell as typed.

### Performance

- **Workspace and tab switches feel instant** — the UI updates in the same frame instead of waiting for the backend round-trip.

## [0.5.0] - 2026-05-19

First public preview. terminux is a cross-platform desktop terminal organized around a Workspaces sidebar and tabbed terminals, inspired by cmux but with a different architecture.

### Workspaces and tabs

- Workspaces sidebar with multiple tabbed terminal sessions per workspace.
- Workspace names track the active shell's working directory automatically; an explicit rename pins the name. Inline rename for both workspaces and tabs.
- Tab titles follow the shell's title escape sequences unless pinned by a manual rename.
- New tabs open in the working directory of the previously active shell.
- Closing the last tab of a workspace closes the workspace and activates another, rather than quitting the app.
- An exited tab can be restarted in place.
- Drag-and-drop reordering of workspaces and tabs, with live drop feedback.

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
- A tab that rings the terminal bell or sends a notification while not in view raises an attention badge that propagates to its workspace.

### Persistence

- Window geometry, sidebar width and collapsed state, and terminal font size persist across launches.
- Each shell's working directory is remembered; on restart every tab respawns its shell in the directory it was in at exit. A directory that no longer exists falls back to the default.

### Input and integration

- Drag a file onto the terminal to insert its full, shell-quoted path.

### Architecture

- Python backend (Starlette/uvicorn on loopback) owning real PTYs, with a TypeScript/xterm.js frontend in a native window; also runnable in a plain browser via `--host`.
- Hardened HTTP responses and a per-session auth token.
- State is saved atomically and versioned; live processes are never persisted — a restored tab always starts a fresh shell.

### Packaging

- macOS `.app` bundle and a Linux bundle. Windows is deferred.
