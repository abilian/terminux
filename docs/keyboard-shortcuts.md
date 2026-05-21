# Keyboard shortcuts

terminux follows the platform convention for the app modifier:

- **Linux** — `Ctrl+Shift+<key>` for everything, including digit jumps.
  Raw `Ctrl+<letter>` flows to the shell unchanged, matching GNOME
  Terminal, Konsole, Alacritty, Ghostty and kitty.
- **macOS** — `Cmd+<key>`. Raw `Ctrl` is left alone so terminal/Emacs
  chords (tmux prefix, fish/zsh history, readline editing) flow straight
  to the shell.

All shortcuts keep working while the terminal has focus.

## Navigation

| Action | Linux | macOS |
| --- | --- | --- |
| Jump to workspace 1–9 | ++ctrl+shift+1++ … ++ctrl+shift+9++ | ++cmd+1++ … ++cmd+9++ |
| Quick switcher (fuzzy, workspaces & tabs) | ++ctrl+shift+p++ | ++cmd+p++ |
| Command palette (commands + actions) | ++f1++ *(provisional)* | ++cmd+shift+p++ |
| Previous / next tab | ++ctrl+shift+bracket-left++ / ++ctrl+shift+bracket-right++ | ++cmd+shift+bracket-left++ / ++cmd+shift+bracket-right++ |
| Previous / next workspace | ++ctrl+shift+up++ / ++ctrl+shift+down++ | ++shift+cmd+up++ / ++shift+cmd+down++ |

The quick switcher fuzzy-matches across every workspace and tab:

![The fuzzy quick switcher overlay listing workspaces and tabs](images/quick-switcher.png){ loading=lazy }

## Workspace & tab lifecycle

| Action | Linux | macOS |
| --- | --- | --- |
| New tab | ++ctrl+shift+t++ | ++cmd+t++ |
| New workspace | ++ctrl+shift+n++ | ++cmd+n++ |
| Close tab / workspace | ++ctrl+shift+w++ | ++cmd+w++ |

Closing the last tab of a workspace closes the workspace and activates another
one rather than quitting the app.

## View

| Action | Linux | macOS |
| --- | --- | --- |
| Toggle sidebar | ++ctrl+shift+b++ | ++cmd+b++ |
| Find in terminal | ++ctrl+shift+f++ | ++cmd+f++ |
| Zoom terminal font in / out | ++ctrl+shift+plus++ / ++ctrl+shift+minus++ | ++cmd+plus++ / ++cmd+minus++ |
| Reset font size | ++ctrl+shift+0++ | ++cmd+0++ |

## Editing

- macOS line-editing chords are supported.
- `Shift+Cmd` + arrow keys for navigation.
- ++shift+enter++ inserts a newline (works with Claude Code and similar tools).

## Selection & links

| Action | Linux | macOS |
| --- | --- | --- |
| Toggle auto-copy on select (iTerm2-style) | ++ctrl+shift+alt+c++ | ++cmd+alt+c++ |
| Open URL under cursor | ++ctrl+click++ | ++cmd+click++ |

Auto-copy is **off by default**; toggling persists the preference across
restarts. Linux users who rely on middle-click paste can leave it off.
