# Keyboard shortcuts

## One set of keys on every platform

Every terminux shortcut is ++ctrl+shift++ plus a key, the same on Linux, Windows and macOS. If you move between machines during the day, your hands don't have to switch.

On macOS, ++cmd++ works too: ++cmd+t++ and ++ctrl+shift+t++ both open a tab. Use whichever you like; the native menus show the ++cmd++ form.

Plain ++ctrl++ belongs to your shell. Shell history, tmux's prefix, readline and Emacs editing all keep working. The exceptions are zoom on Linux and Windows, and copy and paste, below.

All shortcuts work while the terminal has focus.

## Workspaces and tabs

| Action | All platforms | Also on macOS |
| --- | --- | --- |
| New tab | ++ctrl+shift+t++ | ++cmd+t++ |
| New workspace | ++ctrl+shift+n++ | ++cmd+n++ |
| Close tab | ++ctrl+shift+w++ | ++cmd+w++ |
| Jump to workspace 1–9 | ++ctrl+shift+1++ … ++ctrl+shift+9++ | ++cmd+1++ … ++cmd+9++ |
| Previous / next tab | ++ctrl+shift+bracket-left++ / ++ctrl+shift+bracket-right++, or ++ctrl+shift+left++ / ++ctrl+shift+right++ | ++cmd+shift+bracket-left++ / ++cmd+shift+bracket-right++ |
| Previous / next workspace | ++ctrl+shift+up++ / ++ctrl+shift+down++ | ++cmd+shift+up++ / ++cmd+shift+down++ |

Closing the last tab of a workspace closes the workspace and activates another one; the app keeps running. The numbers 1 to 9 are shown next to the workspaces in the sidebar.

## Palettes

| Action | All platforms | Also on macOS |
| --- | --- | --- |
| Quick switcher (fuzzy, workspaces and tabs) | ++ctrl+shift+o++ | ++cmd+p++, ++cmd+shift+o++ |
| Command palette (every command) | ++ctrl+shift+p++ or ++f1++ | ++cmd+shift+p++ |

The quick switcher fuzzy-matches across every workspace and tab:

![The fuzzy quick switcher overlay listing workspaces and tabs](../images/quick-switcher.png){ loading=lazy }

The command palette holds the commands that have no shortcut of their own: sorting the sidebar, usage stats, the remote connection URL, and the toggles.

## View

| Action | All platforms | Also on macOS |
| --- | --- | --- |
| Toggle sidebar | ++ctrl+shift+b++ | ++cmd+b++ |
| Find in terminal | ++ctrl+shift+f++ | ++cmd+f++ |
| Zoom the font in / out | ++ctrl+shift+plus++ / ++ctrl+shift+minus++ | ++cmd+plus++ / ++cmd+minus++ |
| Reset the font size | ++ctrl+shift+0++ | ++cmd+0++ |

On Linux and Windows, zoom also works without Shift (++ctrl+plus++, ++ctrl+minus++, ++ctrl+0++), as in GNOME Terminal and Windows Terminal.

## Copy and paste

| Action | All platforms | Also on Linux and Windows | Also on macOS |
| --- | --- | --- | --- |
| Copy the selection | ++ctrl+shift+c++ | ++ctrl+c++ while text is selected | ++cmd+c++ |
| Paste | ++ctrl+shift+v++ | ++ctrl+v++ | ++cmd+v++ |
| Select all | ++ctrl+shift+a++ | | ++cmd+a++ |
| Toggle auto-copy on selection | ++ctrl+shift+alt+c++ | | ++cmd+alt+c++ |

Plain ++ctrl+c++ copies only while text is selected, and clears the selection. With nothing selected, it interrupts the running program as usual, so pressing it twice always interrupts. This matches Windows Terminal, and means the PC version of ++cmd+c++ / ++cmd+v++ works on any PC. On a Mac, plain ++ctrl+c++ always interrupts. Since terminux takes plain ++ctrl+v++ on Linux and Windows, use ++ctrl+q++ there for what ++ctrl+v++ does in the shell or in vim (insert the next key literally, visual block).

Auto-copy (as in iTerm2) copies whatever you select, without a key. It is off by default and kept across restarts.

On Linux and Windows, the **Edit** menu has the same commands.

## Editing the command line

| Action | macOS | Linux and Windows |
| --- | --- | --- |
| Start / end of line | ++cmd+left++ / ++cmd+right++ | ++home++ / ++end++ |
| Previous / next word | ++option+left++ / ++option+right++ | ++alt+left++ / ++alt+right++ |
| Delete the previous word | ++option+backspace++ | ++alt+backspace++ |
| Delete to the start of the line | ++cmd+backspace++ | ++ctrl+u++ |

In coding agents (Claude Code, Codex, OpenCode, Pi…) and other tools with multi-line input, ++shift+enter++ inserts a newline without running the line.

## Links

++ctrl++-click (++cmd++-click on macOS) opens the URL under the pointer, including the hyperlinks modern tools print.

## Moving between a Mac and a PC

If you stick to ++ctrl+shift++, the shortcuts behave the same everywhere. The differences you may still run into:

- On a Mac, ++cmd+p++ is the quick switcher, but ++ctrl+shift+p++ is the command palette everywhere. Use ++ctrl+shift+o++ for the quick switcher, and it's the same on all three.
- Plain ++ctrl+c++ and ++ctrl+v++ copy and paste on a PC, but go to the shell on a Mac. ++ctrl+shift+c++ and ++ctrl+shift+v++ copy and paste on all three.
- A few shell keys need ++ctrl+shift++ on most keyboards, and terminux takes them on every platform. The one you may miss is `Ctrl+_` (++ctrl+shift+minus++), readline's and Emacs's undo, which zooms out instead.

## In a browser

When terminux runs in a browser tab (`--no-window` or `--server`), the browser keeps some keys for itself and never passes them to the page. On macOS, these are ++cmd+w++, ++cmd+t++ and ++cmd+n++. On Linux and Windows, they are ++ctrl+shift+t++, ++ctrl+shift+w++ and ++ctrl+shift+n++. Firefox also keeps ++ctrl+shift+p++.

- On macOS, ++ctrl+shift++ still works for all of them.
- On Linux and Windows, those shortcuts also work with ++alt+shift++ in a browser tab: ++alt+shift+t++, ++alt+shift+w++, ++alt+shift+n++, ++alt+shift+p++, and ++alt+shift+o++ for the quick switcher. Other ++alt+shift++ keys still reach the shell.
- ++f1++ opens the command palette in every browser.
- In Chrome and Edge, the command palette's **Enter full screen** makes the browser pass every key to terminux, ++cmd+w++ included. Hold ++esc++ to leave full screen.

terminux's own window, and `terminux --connect`, have none of these limits.
