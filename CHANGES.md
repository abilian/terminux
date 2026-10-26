# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.11.0] - 2026-10-25

### Removed

- **macOS 11 (Big Sur) is no longer supported**; terminux needs macOS 12 or later. On Big Sur, pip, pipx and uv keep installing 0.10.1, which still works there.

### Added

- **The same shortcuts on all three platforms.** `Ctrl+Shift` plus a key now works on macOS too, next to `Cmd`, copy and paste included. Linux copies with plain `Ctrl+C` (while text is selected) and pastes with `Ctrl+V`, as Windows does. `F1` opens the command palette everywhere, and `Ctrl+Shift+O` the quick switcher.
- **Shortcuts in a browser tab.** Browsers keep some chords for themselves (Cmd+W, T and N; Ctrl+Shift+T, W and N; Ctrl+Shift+P in Firefox). In a browser tab on Linux and Windows, every shortcut also works with `Alt+Shift`, and the command palette's "Enter full screen" lets Chrome and Edge pass every shortcut through.

### Changed

- **The API is stricter**: creating a workspace or tab answers 201, a 404 names what is missing, numbers and flags must be JSON numbers and booleans, and closing a workspace's last tab is refused (409).
- **An unreadable `server.token` is an error** instead of being replaced silently, which changed the stable URL. A bad saved UI preference falls back to its default instead of setting the whole state file aside.

### Fixed

- **On Linux, a missing GTK or display says what to do** (the packages to install, a `pipx --system-site-packages` reinstall, or `--no-window` and `--server`) instead of a traceback.
- **A window attaching to a terminal no longer types stray escape sequences into it.** It answered the terminal queries in the replayed history (fish asks for the cursor position and colors at each prompt), and those answers reached the program as input: `terminux --connect` launched from a tab printed lines of `^[[?1;2c^[[29;1R…`.
- **A malformed message from a client no longer drops its terminal connection.**
- **Renaming to a blank name goes back to the automatic name** instead of showing "workspace N".
- **A tab reorder that lists a tab twice no longer duplicates it.**
- **Frontend errors and refused changes show in the console** instead of being dropped silently.

## [0.10.1] - 2026-10-13

### Added

- **`terminux --daemon` (`-d`)** prints the URL once the server answers and goes to the background, so you get your prompt back without `nohup`. The window opens as usual; with `--server`, it's a headless server. It logs to the platform's log folder and writes a PID file; `terminux --stop` stops it, as closing the window does. `--public-host` sets the hostname in the printed URL and in "Show remote connection URL". macOS and Linux only.
- **Sort by recent activity.** A sidebar sort for coming back to many workspaces: ready (green) ones first, in the order they finished, then working (amber) ones, then the rest, most recently typed in first. In the command palette and the Workspace menu.

### Changed

- **"Sort by activity" is now "Sort by time spent"**, to tell it apart from the new sort.

### Fixed

- **`--connect` windows and browsers load again with `terminux --server`.** The served page carried a stale access code, so every request was refused.
- **Large scrollbacks are kept.** A tab with more than 2 MB of scrollback lost all of it at restart, and in Chrome, Windows and browser mode, autosaves past 64 KB failed silently. Failed saves are now retried.
- **Closing a tab lets its shell save its history**: the shell gets a hang-up signal before being killed.
- **Ctrl-C, SIGTERM and `terminux --stop` save the layout** and close the shells, as closing the window does; SIGTERM closes the window, if there is one.
- **A corrupt `state.json` is set aside** as `state.json.corrupt` instead of being overwritten.
- **Ctrl+click opens links on Linux and Windows**, as documented (it took Ctrl+Shift+click).
- **Dropped text works from a second window too**, and is pasted like `Ctrl+V`.
- **Malformed API requests get a 400** naming the bad field; out-of-range terminal sizes, which could stall new tabs, are clamped.
- **Access-code guessing is throttled behind a reverse proxy**, where every client looks local.
- **The macOS menu bar has a single View menu.** pywebview added a second one, holding only "Enter Full Screen", which looked like terminux's with most entries missing. "Toggle Full Screen" is now in terminux's View menu.
- **Started from a terminal on macOS, the app is called terminux** in the menu bar, not "Python".
- Memory held by exited shells and by terminals closed in another window is freed.

## [0.10.0] - 2026-10-09

### Added

- **Terminals on Windows** 10 and 11, through ConPTY: PowerShell 7 if installed, else Windows PowerShell, else `cmd`. Everything works as on macOS and Linux, except that the current directory needs the PowerShell snippet from the [shell integration guide](https://terminux.lab.abilian.com/guides/shell-integration/). Windows can also be a `--connect` client. Settings live in `%LOCALAPPDATA%\terminux`.
- **Copy and paste on Windows and Linux**: `Ctrl+Shift+C`, `Ctrl+Shift+V`, `Ctrl+Shift+A`, plus plain `Ctrl+C` (with a selection) and `Ctrl+V` on Windows. A new **Edit** menu has the same commands.
- **Show remote connection URL** (command palette, View menu) gives the `ssh -L` and `terminux --connect` lines to copy, with the port and access code filled in.

### Changed

- **`Ctrl+Shift+P` opens the command palette on Linux and Windows**, as in VS Code; the quick switcher moves to `Ctrl+Shift+O`. `F1` still works.
- **Log lines include a date and time** in every mode; `--debug` and `--trace` add milliseconds.

### Fixed

- **Font zoom works with plain `Ctrl` on Linux and Windows**, and on layouts that put `-` elsewhere (AZERTY).
- **The palette keeps the keyboard while a new tab's shell starts**; typing no longer goes to the shell.
- **Progress bars (`OSC 9;4`) and directory reports (`OSC 9;9`) no longer ring the attention bell.**
- **A second window on the same terminal no longer garbles it.** A terminal follows the window you're using (typing, clicking, focusing); the other may look garbled until you come back to it.
- **macOS no longer throttles hidden windows (App Nap)**, which delayed output and ready dots and could drop connections.
- **No more false "event loop unresponsive" stack dumps** when the whole app was paused by the system.
- **A full disk no longer turns saves into server errors**; the failure is logged and the previous file stays intact.

## [0.9.0] - 2026-09-17

### Changed

- "Reorder by activity" is now "Sort by activity", so it can't be confused with drag-and-drop reordering.
- **The usage-stats overlay updates live** while it's open.

### Fixed

- **Renaming no longer swallows the first keystroke** typed right after the double-click.

### Internal

- The frontend's chrome is rendered with Preact, so background refreshes no longer disturb typing or dragging. Frontend modules are grouped into layers, and frontend tests grew from 27 to 80.

## [0.8.1] - 2026-08-30

### Added

- **You can always see which workspace you're in.** With the sidebar hidden, the active workspace appears as a chip at the left of the tab bar (click it to bring the sidebar back), and its name is in the window title.

## [0.8.0] - 2026-08-30

### Added

- **Terminals reconnect automatically** after a lost connection (backend stall, network blip, sleep), with backoff, and repaint from the server's buffer. Tabs used to stay dead until the app was reopened.
- **`--debug` enables the web inspector** in the desktop window (right-click → Inspect Element).

### Fixed

- **Web/remote mode: the page no longer reveals the access code.** Every route now requires the code.
- **A stale browser tab can no longer lock you out**: local connections are exempt from the lockout.
- **Terminals open again on older Macs** (e.g. Big Sur), in the app, a `--connect` client or a browser: the build targets Safari 14-era WebKit again, and the security policy names the websocket origin.
- **Hyperlinks printed by programs open** with Cmd/Ctrl+click, like plain URLs, instead of a dead popup. Only `http`, `https` and `mailto` links open.
- **Starting on a port already in use fails with a clear error** instead of hanging.
- **Access codes no longer appear in request logs** with `--debug` or `--trace`.

### Internal

- The controller never holds its state lock across a disk write, and shells are forked off the event loop, closing the remaining freeze vectors.

## [0.7.2] - 2026-07-29

### Added

- **Remote access.** `terminux --server` on a host and `terminux --connect <url>` on your laptop: the normal window, with every shell on the server, so builds keep going when you close the lid. Access is protected by a short persistent code, rate-limited against guessing; the recommended setup goes through an SSH port-forward. See the [remote access guide](https://terminux.lab.abilian.com/guides/remote/).

### Fixed

- **Pasting into a program that isn't reading input no longer freezes the app**; only that terminal waits.
- **A rare freeze of all terminals while idle** is fixed: reading terminal output can no longer stall the server.
- **Very large pastes are no longer truncated.**

### Internal

- Terminal I/O is non-blocking end to end.

## [0.7.1] - 2026-06-03

### Fixed

- **An unresponsive external or network drive no longer freezes the app (macOS).** The directory lookup now uses a kernel call that cannot hang, and slow disk saves no longer stall the terminals.

### Added

- **The app diagnoses its own stalls**: a server unresponsive for ~3 s logs a snapshot of what it was doing. `kill -INFO <pid>` (macOS) or `kill -USR1 <pid>` (Linux) requests one at any time, and slow disk operations are flagged.
- **`--debug` and `--trace` flags** for verbose logging.

## [0.7.0] - 2026-05-28

### Added

- **Native application menu** (File, View, Workspace, Help), wired to the same actions as the shortcuts and the command palette. Help → Documentation opens the docs.
- **App icon**: a `>_` prompt on a dark rounded square, instead of the Python rocket in the macOS dock.

## [0.6.3] - 2026-05-28

### Fixed

- Renaming a workspace or tab is no longer interrupted by the background refresh: the edit stays open until you press Enter (save) or Escape (cancel).

## [0.6.2] - 2026-05-27

### Changed

- **A single attention indicator.** The sidebar 🔔 bell badge is gone; the colored dot is now the only signal. The dot turns green ("ready") only when a task actually finishes (a command ending, a build completing, an interactive tool returning to its prompt), and this works with or without shell integration. Mere output no longer marks a workspace as ready.

### Fixed

- The dot no longer flashes in the first few seconds after you switch away from a workspace.
- Fixed a flicker where the ready indicator could briefly reappear right after you visited a workspace.

## [0.6.1] - 2026-05-26

### Changed

- **Workspace names follow the first tab's directory**, whichever tab is active. Switching between tabs no longer keeps renaming the workspace; drag a different tab into the first slot to hand it the naming role.

### Fixed

- **Idle programs no longer keep the busy dot amber.** A tool sitting at its prompt (vim, less, Claude Code waiting for input) now releases the dot once it goes quiet. Tradeoff: a long-running command that prints nothing may briefly read as idle until it produces output again.
- **A still-working task no longer shows as ready.** Spinner-style output kept turning the dot green while the task was running; busy now takes precedence.
- **Rapid workspace switching no longer misfires.** Holding `Cmd+Shift+Arrow` could occasionally jump you back to a workspace you had already left.

## [0.6.0] - 2026-05-22

### Added

- Per-workspace **active-time tracking** for the current session, with an inline column in the sidebar, a dedicated stats overlay, and a command palette (`Cmd+Shift+P` on macOS, `F1` on Linux) exposing "Display usage stats", "Reorder sidebar by activity", "Reset session activity counters", and toggles for auto-copy-on-select and scrollback persistence.
- Amber **"busy" dot** in the sidebar when a workspace has a foreground task running. It uses shell-integration signals when available, otherwise by watching the shell's foreground process.
- **Scrollback persistence**: each tab's last ~5000 lines are saved and replayed into the fresh shell after a restart, under a dim "session resumed @ <time>" separator. Capped at 2 MB per tab, dropped when you close a tab yourself, and can be turned off from the command palette.
- **Numbered workspace slots** in the sidebar (1-9) surface the matching jump shortcut.
- **Clickable URLs**: `Cmd`-click (macOS) or `Ctrl`-click (Linux) opens links in your default browser.
- **Auto-copy on selection** (iTerm2-style), off by default, toggleable from the command palette.
- **Quit confirmation** so an accidental `Cmd+Q` / `Ctrl+Q` doesn't drop live shells.
- **Shell-integration snippets** for bash / zsh / fish, for more precise busy/ready detection. See `docs/src/guides/shell-integration.md`.
- **macOS permission (TCC) troubleshooting** section in `docs/src/developers/packaging.md`.

### Changed

- Linux app shortcuts now use `Ctrl+Shift+<key>` (matching GNOME Terminal, Konsole, and Alacritty), leaving plain `Ctrl+<key>` for the shell; workspace jumps are `Ctrl+Shift+1..9`. macOS keeps `Cmd+<key>`.
- Docs and the launch blog post reframed as **Linux first, macOS second**.
- Shell title updates no longer raise the attention badge; only a real bell, a desktop-style notification, or a finished command does.

### Fixed

- **Restored scrollback no longer comes back garbled** after a restart.
- **Fixed a race that could corrupt workspace/tab state** when two actions landed at the same moment.
- **Holding a key now repeats it** in vim / less / fzf on macOS (press-and-hold accent popup disabled inside the terminal).
- **The stats overlay closes on Escape.**
- **Tab bar overflow**: tabs shrink gracefully as more open, while the `+` button stays visible.
- **macOS no longer mis-fires `Ctrl+P` / `Ctrl+B` as app shortcuts**: they reach the shell as typed.

### Performance

- **Workspace and tab switches feel instant**: the UI updates in the same frame, without waiting for the backend round-trip.

## [0.5.0] - 2026-05-19

First public preview. terminux is a cross-platform desktop terminal organized around a Workspaces sidebar and tabbed terminals.

### Workspaces and tabs

- Workspaces sidebar with multiple tabbed terminal sessions per workspace.
- Workspace names track the active shell's working directory automatically; an explicit rename pins the name. Inline rename for both workspaces and tabs.
- Tab titles follow the shell's title escape sequences unless pinned by a manual rename.
- New tabs open in the working directory of the previously active shell.
- Closing the last tab of a workspace closes the workspace and activates another; the app keeps running.
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
- State is saved atomically and versioned; live processes are never persisted, so a restored tab always starts a fresh shell.

### Packaging

- macOS `.app` bundle and a Linux bundle. Windows is deferred.
