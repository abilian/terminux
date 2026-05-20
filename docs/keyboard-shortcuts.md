# Keyboard shortcuts

Shortcuts keep working while the terminal has focus. Use ++cmd++ on macOS and
++ctrl++ on Linux.

## Navigation

| Action | macOS | Linux |
| --- | --- | --- |
| Jump to workspace 1–9 | ++cmd+1++ … ++cmd+9++ | ++ctrl+1++ … ++ctrl+9++ |
| Quick switcher (fuzzy, workspaces & tabs) | ++cmd+p++ | ++ctrl+p++ |
| Previous / next tab | ++cmd+shift+bracket-left++ / ++cmd+shift+bracket-right++ | ++ctrl+shift+bracket-left++ / ++ctrl+shift+bracket-right++ |

The quick switcher fuzzy-matches across every workspace and tab:

![The fuzzy quick switcher overlay listing workspaces and tabs](images/quick-switcher.png){ loading=lazy }

## Workspace & tab lifecycle

| Action | macOS | Linux |
| --- | --- | --- |
| New tab | ++cmd+t++ | ++ctrl+t++ |
| New workspace | ++cmd+n++ | ++ctrl+n++ |
| Close tab / workspace | ++cmd+w++ | ++ctrl+w++ |

Closing the last tab of a workspace closes the workspace and activates another
one rather than quitting the app.

## View

| Action | macOS | Linux |
| --- | --- | --- |
| Toggle sidebar | ++cmd+b++ | ++ctrl+b++ |
| Find in terminal | ++cmd+f++ | ++ctrl+f++ |
| Zoom terminal font in / out | ++cmd+plus++ / ++cmd+minus++ | ++ctrl+plus++ / ++ctrl+minus++ |

## Editing

- macOS line-editing chords are supported.
- `Shift+Cmd` + arrow keys for navigation.
- ++shift+enter++ inserts a newline (works with Claude Code and similar tools).

## Selection & links

| Action | macOS | Linux |
| --- | --- | --- |
| Toggle auto-copy on select (iTerm2-style) | ++cmd+alt+c++ | ++ctrl+alt+c++ |
| Open URL under cursor | ++cmd+click++ | ++ctrl+click++ |

Auto-copy is **off by default**; toggling persists the preference across
restarts. Linux users who rely on middle-click paste can leave it off.
