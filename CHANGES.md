# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.0] - 2026-10-09

### Added

- **Terminals on Windows.** terminux now runs its own shells on Windows 10 and 11, through the system's pseudo console (ConPTY): PowerShell 7 if it's installed, else Windows PowerShell, else `cmd`. Tabs, resizing, scrollback, restarting an exited shell, the busy and ready dots, and the remote `--connect` windows work as on macOS and Linux. Closing a tab ends its shell and whatever runs in its console; programs that opened a window of their own (`Start-Process notepad`) keep running, as in Windows Terminal. Windows offers no way to read another program's current directory, so the workspace name and "new tab in the same directory" need the shell to report it: the [shell integration guide](https://terminux.lab.abilian.com/guides/shell-integration/) has a PowerShell snippet for that, which also brings the precise busy/ready signals. A Windows machine can also be a client (`terminux --connect <url>`) of a terminux server on a Mac or a Linux box. Settings live in `%LOCALAPPDATA%\terminux`.
- **Sort by recent activity.** A new sidebar sort for coming back to a dozen workspaces: ready (green) ones first, in the order they finished, then working (amber) ones, then the rest, the one you last typed in first. terminux now remembers when you last typed in each workspace, across restarts. It's in the command palette and the Workspace menu.
- **Copy and paste on Windows and Linux.** `Ctrl+Shift+C` copies the selection, `Ctrl+Shift+V` pastes, and `Ctrl+Shift+A` selects everything; on Windows, plain `Ctrl+C` (while text is selected) and `Ctrl+V` work too, as in Windows Terminal. A new **Edit** menu has the same commands. Until now, only macOS had copy and paste shortcuts, through its system Edit menu.
- **A command that tells you how to connect from another machine.** The command palette (and View menu) now has **Show remote connection URL**: it names this machine, works out whether the server is reachable from the network or needs an SSH tunnel, and hands you the `ssh -L` and `terminux --connect` lines to copy, with the live port and access code already filled in. It also warns when the address will stop working at the next restart, and points at `terminux --server` for one that lasts.

### Changed

- **"Sort by activity" is now "Sort by time spent"**, so it can't be confused with the new "Sort by recent activity". It still puts the workspaces you've used most this session first.
- **`Ctrl+Shift+P` now opens the command palette on Linux and Windows**, as in VS Code and Windows Terminal. The quick switcher moves from `Ctrl+Shift+P` to `Ctrl+Shift+O`. `F1` still opens the command palette, and macOS keeps `Cmd+Shift+P` and `Cmd+P`.
- **Log lines now include a date and time** in every mode (they used to need `--debug`), so a log from a long-running instance can be matched against what happened when. `--debug` and `--trace` add milliseconds.

### Fixed

- **Font zoom works with plain `Ctrl` on Linux and Windows.** `Ctrl+=`, `Ctrl+-` and `Ctrl+0` now zoom and reset the terminal font, as in GNOME Terminal and Windows Terminal; before, only the `Ctrl+Shift` versions did. Zoom also follows the character you type, so it works on layouts that put `-` elsewhere (on a French AZERTY keyboard, it's on the 6 key).
- **The palette keeps the keyboard while a shell is still starting.** Opening the palette (or a rename, or find) before a new tab's shell had finished starting let the terminal take the focus back as soon as it was ready, so what you typed next went to the shell.
- **Progress bars and directory reports no longer ring the attention bell.** Programs that report progress with `OSC 9;4` (winget, and more and more tools on every platform), and prompts that report their directory with `OSC 9;9` (oh-my-posh, Starship), lit the sidebar's attention dot at every update, as if they were notifications. Only plain `OSC 9;<message>` notifications count now.
- **Screens no longer get garbled when a second window shows the same terminal.** With a `--connect` window open on another machine, terminals on the main machine could fill with text in the wrong places (shells, Claude Code, any full-screen program), and only closing the tab fixed it. A terminal has a single size; the remote window was imposing its own without any sign of it. Each terminal now follows the window you are actually using: typing, clicking, focusing the window, or switching to the tab makes it the owner, and the programs redraw for it. The window you're not using may look garbled until you come back to it, and then it snaps back. Stray automatic replies from the unused window (which could show up as junk like `^[[24;1R` in a prompt) no longer reach your programs.
- **Hidden terminux windows no longer get throttled by macOS (App Nap).** When the window was covered, minimized, or the display slept while the Mac stayed awake, macOS slowed terminux down: hidden tabs' output was handled late, the green "ready" dot appeared late, and connections could drop and reconnect when you came back. terminux now opts out of App Nap while its window is open. It still lets the Mac go to sleep.
- **No more false "event loop unresponsive" alarms.** When the whole app was paused by the system (App Nap, heavy swapping, a debugger), the freeze watchdog mistook the pause for a frozen server and wrote a full stack dump every few seconds; one field log grew to 4.4 MB of them. It now recognizes a system-wide pause and logs a single line, keeping stack dumps for real freezes.
- **A full disk no longer turns saves into server errors.** When the disk had no room left even to create a temporary file, a scrollback or layout save escaped its error handling and failed the request. It is now logged like any other failed save; the previous saved file stays intact and the next save retries.

## [0.9.0] - 2026-09-17

### Changed

- "Reorder by activity" is now called "Sort by activity" in the menu and command palette, so it can't be confused with drag-and-drop reordering.
- **The usage-stats overlay updates live.** Leave it open and the per-workspace times and bars tick along with your activity; they used to freeze at whatever they showed when the overlay opened.

### Fixed

- **Renaming no longer swallows the first keystroke.** Typing immediately after double-clicking a workspace or tab name could lose the first character to a focus race; the rename input is now focused before any keystroke can land.

### Internal

- The frontend's chrome (sidebar, tab bar, palettes, stats, find) is now rendered with Preact, which retires the hand-written "don't repaint while the user is typing or dragging" guards: background refreshes patch the existing DOM in place, and the two palettes share one fuzzy-overlay component. Frontend modules are grouped into `state/`, `term/`, `ui/`, `input/`, and `util/` layers; frontend unit tests grew from 27 to 80 (`make frontend-cov` reports coverage), and `make help` lists every target.

## [0.8.1] - 2026-08-30

### Added

- **You can always see which workspace you're in.** With the sidebar hidden (`Cmd/Ctrl+B`), the active workspace's status dot, number, and name now appear as a chip at the left of the tab bar; clicking it brings the sidebar back. The window and browser-tab title also show the workspace name, so the answer to "where am I?" stays visible even when the app is minimized.

## [0.8.0] - 2026-08-30

### Added

- **Terminals now reconnect automatically.** A lost connection (a backend stall, a network blip, a laptop waking from sleep) used to leave tabs permanently dead even though the shells were fine; the only cure was reopening the app. Each terminal now shows "[connection lost — reconnecting…]", redials with backoff until the server answers, and repaints from the server's output buffer. This is what makes remote mode's "disconnect and come back later" actually hold.
- **`--debug` now also opens the door to frontend debugging** in the desktop window: right-click → Inspect Element brings up the web inspector.

### Fixed

- **Web/remote mode: the page no longer reveals the access code.** Fetching the app's address without a valid code used to return the page with the code embedded in it, so anyone who could reach the port could let themselves in. Every route now requires the code; your own links (which always include it) are unaffected.
- **A stale browser tab can no longer lock you out.** Requests with an outdated code from your own machine could trip the brute-force guard and block the real window for a minute at a time. Local connections are now exempt from the lockout, which still protects servers exposed to a network.
- **Terminals open again on older Macs.** Two stacked problems broke every shell on e.g. Big Sur while the rest of the UI worked: a dependency upgrade had raised the frontend's minimum browser requirement past the WebKit that older macOS versions ship, and the security policy only declared `connect-src 'self'`, which older engines refuse to apply to websockets, so even a working terminal couldn't attach its data stream. The terminal library is pinned back to its proven line, the build explicitly targets Safari-14-era WebKit, and the policy now names the websocket origin explicitly. Applies wherever an older engine renders the UI: the desktop app, a `--connect` client, or a browser.
- **Hyperlinks printed by programs now open.** Clicking a link a program emitted as a real terminal hyperlink (Claude Code's artifact URLs, `ls --hyperlink`, modern CLI tools) used to show a browser warning popup whose OK button then did nothing. Such links now behave exactly like plain-text URLs: Cmd+click (macOS) / Ctrl+click (Linux) opens them in your default browser, with no popup; only `http`, `https`, and `mailto` links are ever opened.
- **Starting on a port that's already in use now fails with a clear error.** It used to hang forever with no output.
- **Access codes no longer appear in request logs** when running with `--debug` or `--trace`.

### Internal

- The controller never holds its state lock across a disk write, and new shells are forked off the event loop. This closes the remaining freeze vectors found in a full audit. For anyone stuck on an older build, `notes/05-lessons-learned.md` documents how to unfreeze a live server without killing it.

## [0.7.2] - 2026-07-29

### Added

- **Remote access.** Run terminux on one machine and use it from another. Start `terminux --server` on the host and `terminux --connect <url>` on your laptop: you get the normal desktop window, but every shell lives on the server: long-running builds keep going while you close the lid, change networks, or switch devices. Access is protected by a short persistent code (`abc-def-ghi` style, rate-limited against guessing); the recommended setup keeps the server private behind an SSH port-forward. Dragging files into a remote window pastes their paths, same as locally. Full guide: `docs/src/guides/remote.md`.

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

- **The app now diagnoses its own stalls.** If the server stops responding for more than ~3 seconds, it automatically logs a warning with a snapshot of what it was doing at the time, so a freeze report comes with evidence attached. You can request the same snapshot at any moment with `kill -INFO <pid>` (macOS) or `kill -USR1 <pid>` (Linux), and disk operations that turn suspiciously slow are flagged in the log before they escalate into a freeze.
- **`--debug` and `--trace` flags** for verbose logging when investigating or reporting a problem. See `docs/src/developers/developing.md#debugging-knobs`.

## [0.7.0] - 2026-05-28

### Added

- **Native application menu.** File / View / Workspace / Help: everything the keyboard shortcuts can do, now discoverable at a glance. On macOS it lives in the global menu bar, on Linux in the window frame. Menu items, keyboard shortcuts, and the command palette all trigger the same actions, so they can't drift apart. Help → Documentation opens the docs in your default browser.
- **App icon.** A stylized `>_` prompt on a dark rounded square appears in the Finder and dock on macOS, and in the window/taskbar on Linux. Launching from the CLI on macOS no longer shows the generic Python rocket in the dock.

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
