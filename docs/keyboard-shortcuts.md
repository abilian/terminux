# Keyboard shortcuts

terminux follows the platform convention for the app modifier:

- **macOS** — `Cmd+<key>`. Raw `Ctrl` is left alone so terminal/Emacs
  chords (tmux prefix, fish/zsh history, readline editing) flow straight
  to the shell.
- **Linux** — `Ctrl+Shift+<key>` for everything, including digit jumps.
  Raw `Ctrl+<letter>` flows to the shell unchanged, matching GNOME
  Terminal, Konsole, Alacritty, Ghostty and kitty.

All shortcuts keep working while the terminal has focus.

## Navigation

| Action | macOS | Linux |
| --- | --- | --- |
| Jump to workspace 1–9 | ++cmd+1++ … ++cmd+9++ | ++ctrl+shift+1++ … ++ctrl+shift+9++ |
| Quick switcher (fuzzy, workspaces & tabs) | ++cmd+p++ | ++ctrl+shift+p++ |
| Command palette (commands + actions) | ++cmd+shift+p++ | ++f1++ *(provisional)* |
| Previous / next tab | ++cmd+shift+bracket-left++ / ++cmd+shift+bracket-right++ | ++ctrl+shift+bracket-left++ / ++ctrl+shift+bracket-right++ |
| Previous / next workspace | ++shift+cmd+up++ / ++shift+cmd+down++ | ++ctrl+shift+up++ / ++ctrl+shift+down++ |

The quick switcher fuzzy-matches across every workspace and tab:

![The fuzzy quick switcher overlay listing workspaces and tabs](images/quick-switcher.png){ loading=lazy }

## Workspace & tab lifecycle

| Action | macOS | Linux |
| --- | --- | --- |
| New tab | ++cmd+t++ | ++ctrl+shift+t++ |
| New workspace | ++cmd+n++ | ++ctrl+shift+n++ |
| Close tab / workspace | ++cmd+w++ | ++ctrl+shift+w++ |

Closing the last tab of a workspace closes the workspace and activates another
one rather than quitting the app.

## View

| Action | macOS | Linux |
| --- | --- | --- |
| Toggle sidebar | ++cmd+b++ | ++ctrl+shift+b++ |
| Find in terminal | ++cmd+f++ | ++ctrl+shift+f++ |
| Zoom terminal font in / out | ++cmd+plus++ / ++cmd+minus++ | ++ctrl+shift+plus++ / ++ctrl+shift+minus++ |
| Reset font size | ++cmd+0++ | ++ctrl+shift+0++ |

## Editing

- macOS line-editing chords are supported.
- `Shift+Cmd` + arrow keys for navigation.
- ++shift+enter++ inserts a newline (works with Claude Code and similar tools).

## Selection & links

| Action | macOS | Linux |
| --- | --- | --- |
| Toggle auto-copy on select (iTerm2-style) | ++cmd+alt+c++ | ++ctrl+shift+alt+c++ |
| Open URL under cursor | ++cmd+click++ | ++ctrl+click++ |

Auto-copy is **off by default**; toggling persists the preference across
restarts. Linux users who rely on middle-click paste can leave it off.
