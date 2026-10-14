# Configuration

terminux has no dotfile. Every preference is changed from inside the app (command palette, menu, or shortcut) and persists server-side automatically, so it stays set across restarts and applies to every window on the same backend.

## Preferences

| Preference | How to change it | Default |
| --- | --- | --- |
| Terminal font size | `Cmd`/`Ctrl+Shift` + `+` / `-` / `0`, or View → Zoom | 13 px |
| Sidebar width | Drag the divider | 220 px |
| Sidebar shown/hidden | `Cmd/Ctrl+B` (the workspace chip stands in when hidden) | shown |
| Auto-copy on selection (iTerm2-style) | Command palette, or `Ctrl+Shift+Alt+C` / `Cmd+Alt+C` | off |
| Scrollback persistence | Command palette or View menu | on |
| Window size and position | Just move/resize the window | 1100 × 720 |

The command palette is `Ctrl+Shift+P` (or `F1`) on Linux and Windows and `Cmd+Shift+P` on macOS; the full chord list is in [Keyboard shortcuts](../guides/keyboard-shortcuts.md). It also lists **Show remote connection URL**, which prints the exact commands another machine needs to reach this one (see [Remote access](../guides/remote.md)).

## Where state lives

All persistent state sits in one directory:

| Platform | Location |
| --- | --- |
| macOS | `~/Library/Application Support/terminux/` |
| Linux | `~/.local/share/terminux/` |
| Windows | `%LOCALAPPDATA%\terminux\` |

Inside it: `state.json` (workspaces, tabs, UI preferences; written atomically and versioned), `scrollback/<tab>.ansi` (one capped file per tab, deleted when the tab closes), `server.token` (only in `--server` mode), and `state.json.corrupt` if a damaged `state.json` was ever found at startup (terminux sets it aside and starts fresh, so you can recover your workspaces from it). Deleting the directory resets terminux completely.

Scrollback files can contain secrets a command echoed; they stay local, are capped at 2 MB per tab, and disappear when persistence is toggled off or the tab is closed.

## Command-line flags

| Flag | What it does |
| --- | --- |
| `--no-window` | Server only; open the printed URL in any browser (dev/test path, web-mode preview) |
| `--server` | Headless server with a persistent access token; pair with `--connect` |
| `-d`, `--daemon` | Goes to the background once the server answers, after printing the URL; the window opens as usual, or none with `--server`. Logs to a file and writes a PID file (macOS, Linux) |
| `--stop` | Stops the terminux started by `--daemon` (closing its window, if any) and waits until it's gone |
| `--public-host NAME` | Hostname or address printed in the URL by `--server` and `--daemon`, so it works from other machines |
| `--connect URL` | Desktop window attached to a remote server ([Remote access](../guides/remote.md)) |
| `--host`, `--port` | Bind address and port (defaults: loopback; port 8443 with `--daemon`, else ephemeral) |
| `--debug`, `--trace` | Diagnostics; see [Debugging knobs](../developers/developing.md#debugging-knobs) |

## Environment seen by your shells

Every shell terminux spawns gets `TERM=xterm-256color`, `TERMINUX=1`, and `TERM_PROGRAM=terminux`. The last one is the guard used by the [shell integration](../guides/shell-integration.md) snippets, and by any customization of your own that should apply only inside terminux.
