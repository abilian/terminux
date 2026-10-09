# Keyboard shortcuts

terminux follows the platform convention for the app modifier:

- **Linux and Windows**: `Ctrl+Shift+<key>` for everything, including
  digit jumps. A raw `Ctrl+<letter>` chord flows to the shell unchanged,
  matching GNOME Terminal, Konsole, Alacritty, Ghostty, kitty and Windows
  Terminal. The zoom keys also work without Shift, as in GNOME Terminal and
  Windows Terminal.
- **macOS**: `Cmd+<key>`. Raw `Ctrl` is left alone so terminal/Emacs
  chords (tmux prefix, fish/zsh history, readline editing) flow straight
  to the shell.

All shortcuts keep working while the terminal has focus.

## Navigation

| Action | Linux & Windows | macOS |
| --- | --- | --- |
| Jump to workspace 1–9 | ++ctrl+shift+1++ … ++ctrl+shift+9++ | ++cmd+1++ … ++cmd+9++ |
| Quick switcher (fuzzy, workspaces & tabs) | ++ctrl+shift+o++ | ++cmd+p++ |
| Command palette (commands + actions) | ++ctrl+shift+p++ or ++f1++ | ++cmd+shift+p++ |
| Previous / next tab | ++ctrl+shift+bracket-left++ / ++ctrl+shift+bracket-right++ | ++cmd+shift+bracket-left++ / ++cmd+shift+bracket-right++ |
| Previous / next workspace | ++ctrl+shift+up++ / ++ctrl+shift+down++ | ++shift+cmd+up++ / ++shift+cmd+down++ |

The quick switcher fuzzy-matches across every workspace and tab:

![The fuzzy quick switcher overlay listing workspaces and tabs](../images/quick-switcher.png){ loading=lazy }

## Workspace & tab lifecycle

| Action | Linux & Windows | macOS |
| --- | --- | --- |
| New tab | ++ctrl+shift+t++ | ++cmd+t++ |
| New workspace | ++ctrl+shift+n++ | ++cmd+n++ |
| Close tab / workspace | ++ctrl+shift+w++ | ++cmd+w++ |

Closing the last tab of a workspace closes the workspace and activates another
one rather than quitting the app.

## View

| Action | Linux & Windows | macOS |
| --- | --- | --- |
| Toggle sidebar | ++ctrl+shift+b++ | ++cmd+b++ |
| Find in terminal | ++ctrl+shift+f++ | ++cmd+f++ |
| Zoom terminal font in / out | ++ctrl+plus++ / ++ctrl+minus++ (Shift optional) | ++cmd+plus++ / ++cmd+minus++ |
| Reset font size | ++ctrl+0++ (Shift optional) | ++cmd+0++ |

## Editing

- macOS line-editing chords are supported.
- `Shift+Cmd` + arrow keys for navigation.
- ++shift+enter++ inserts a newline (works with Claude Code and similar tools).

## Selection & links

| Action | Linux & Windows | macOS |
| --- | --- | --- |
| Copy the selection | ++ctrl+shift+c++ | ++cmd+c++ |
| Paste | ++ctrl+shift+v++ | ++cmd+v++ |
| Select all | ++ctrl+shift+a++ | ++cmd+a++ |
| Toggle auto-copy on select (iTerm2-style) | ++ctrl+shift+alt+c++ | ++cmd+alt+c++ |
| Open URL under cursor | ++ctrl+click++ | ++cmd+click++ |

On Windows, plain ++ctrl+c++ also copies while text is selected (and interrupts the running program otherwise), and plain ++ctrl+v++ pastes, as in Windows Terminal. The **Edit** menu has the same commands on Windows and Linux.

Auto-copy is **off by default**; toggling persists the preference across
restarts. Linux users who rely on middle-click paste can leave it off.
