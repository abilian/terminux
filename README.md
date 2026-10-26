<div align="center">

# terminux

### A fast, reliable, cross-platform terminal, organized the way you actually work.

**Workspaces sit on the left, tabbed terminals in the middle, and everything stays where you left it.**

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#install--package)
[![PyPI](https://img.shields.io/pypi/v/terminux.svg)](https://pypi.org/project/terminux/)
[![Status](https://img.shields.io/badge/status-0.11%20preview-orange.svg)](#status-011-preview)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

<br/>

<img src="https://git.sr.ht/~sfermigier/terminux/blob/main/docs/src/images/main-window.png" alt="terminux: five workspaces in the sidebar, a finished test run in the active one" width="720"/>

</div>

---

## Why terminux?

You have *six* projects on the go. Each one has its own directory, its own running server, its own test suite and its own half-finished command. By mid-afternoon they are spread across a dozen terminal windows, and finding the one where the build just finished means clicking through all of them.

terminux gives each project a home (a **workspace** in a sidebar) with its own tabs of real shells. A small dot tells you what's happening in each workspace. The whole layout comes back after a restart, scrollback included. You need no account, terminux sends no telemetry, and it has no AI features: it's just a terminal that respects your flow.

## Try it

terminux is on PyPI. It runs on macOS 12 or later, Linux and Windows 10/11, with Python 3.12 or later (macOS 11 stays on 0.10.1):

```sh
uvx terminux                  # try it without installing
uv tool install terminux      # or install it
```

On Linux, the window needs your distribution's GTK and WebKitGTK packages, and terminux installed with `pipx install --python /usr/bin/python3 --system-site-packages terminux`; see [Installation](docs/src/getting-started/index.md#on-linux). terminux tells you what's missing if you skip this.

## ✨ What you get

- **One workspace per project.** A sidebar of named workspaces, each with its own tabs. A workspace names itself after its first tab's directory (rename it to pin your own name). `Cmd+1..9` on macOS, `Ctrl+Shift+1..9` on Linux and Windows jumps straight to one.
- **Know when something is done.** Each workspace's dot works like a traffic light: **amber** while a task is running there, **green** once it finishes while you were elsewhere. It works out of the box; the optional [shell integration](docs/src/guides/shell-integration.md) makes it exact.
- **Everything comes back.** Quit and reopen: workspaces, tabs, window size, font size, each tab's directory and *the visible scrollback of every tab* are restored. The shells are fresh; the view is the one you left.
- **Nothing pauses in the background.** A server keeps logging and a build keeps building while you work in another workspace.
- **Keyboard-first.** A fuzzy quick switcher for workspaces and tabs, a command palette, find-in-terminal, font zoom. The same `Ctrl+Shift` shortcuts work on Linux, Windows and macOS (as in GNOME Terminal and Windows Terminal), and `Cmd` works too on macOS, so your shell keeps its own `Ctrl` keys.
- **Know where you are.** Hide the sidebar for more room and the current workspace's name stays visible in the tab bar; the window title shows it too.
- **Your shells on another machine.** Run terminux as a server and connect from your laptop. Close the lid, change networks, come back later: terminals reconnect on their own and repaint what happened. See [Remote access](docs/src/guides/remote.md).
- **The small things.** Copy and paste with `Ctrl+Shift+C` / `Ctrl+Shift+V` (`Cmd+C` / `Cmd+V` on macOS; plain `Ctrl+C` / `Ctrl+V` also work on Linux and Windows), `Cmd`/`Ctrl`+click opens links (including the hyperlinks modern tools print), `Shift+Enter` inserts a newline in coding agents (Claude Code, Codex, OpenCode, Pi…) and other tools with multi-line input, drag and drop reorders workspaces and tabs, dropping a file pastes its path, and copy-on-select is one toggle away.
- **Local and sturdy.** Everything stays on your machine, in readable local files. It listens only on your machine unless you ask otherwise, a stuck program can't freeze the app, and saves are atomic.

<div align="center">

<img src="https://git.sr.ht/~sfermigier/terminux/blob/main/docs/src/images/restored.png" alt="After a restart: the previous test run, a 'session resumed' line, and a fresh prompt" width="720"/>

<sub>After a restart, the previous session's output sits above a <code>session resumed</code> line, with a fresh shell below.</sub>

<br/><br/>

<img src="https://git.sr.ht/~sfermigier/terminux/blob/main/docs/src/images/quick-switcher.png" alt="The fuzzy quick switcher, filtered on 'api'" width="720"/>

<sub>The quick switcher (<code>Cmd+P</code> on macOS, <code>Ctrl+Shift+O</code> on Linux and Windows): jump to any workspace or tab.</sub>

</div>

## Run from source

```sh
uv sync
make frontend                # build the web UI (needs Node; first run only)
uv run terminux              # desktop window (pywebview)
uv run terminux -d           # same, in the background (macOS, Linux)
uv run terminux --no-window  # server only; open the printed URL in a browser
uv run terminux --debug      # verbose logs + slow-op warnings
uv run terminux --trace      # extreme: log every save/load/cwd lookup
```

`--no-window` serves the same UI to any browser, handy for development and for running terminux where no display is available. `--debug` and `--trace` are diagnostics flags; see [**Debugging knobs**](docs/src/developers/developing.md#debugging-knobs).

### Remote mode

Run terminux on a headless server and connect from your laptop:

```sh
# on the server: start it in the background (port 8443 by default)
terminux --server --daemon
# prints: terminux server listening — connect with:
#           http://127.0.0.1:8443/?t=abc-def-ghi

# on the laptop (one shell)
ssh -L 8443:localhost:8443 server.example.com

# on the laptop (another shell)
uv run terminux --connect http://localhost:8443/?t=abc-def-ghi

# on the server, when you're done
terminux --stop
```

Shells, workspaces, and scrollback live on the server: disconnect, sleep the laptop, reconnect later, everything's where you left it. Without `--daemon`, `terminux --server` stays in the foreground (for systemd or launchd), and `--host 0.0.0.0 --public-host <name>` skips the tunnel on a trusted network. See [**Remote access**](docs/src/guides/remote.md) for the full recipe (multi-client, firewall guidance, systemd service).

## Install / package

terminux ships as a self-contained desktop app; no Python or Node required to run the bundle.

```sh
make build-linux  # Linux bundle (built in Docker) → dist/linux/terminux/terminux
make docker-run   # run headless web mode on :8000
make build-macos  # macOS .app → dist/terminux.app
```

The [**documentation**](#documentation) has the full platform notes (signing, Gatekeeper, X11, architectures).

## Documentation

Docs are built with [Zensical](https://zensical.org/); sources live in `docs/src/`, configuration in `docs/zensical.toml`.

```sh
make docs-serve    # live preview at http://127.0.0.1:8000
make docs          # static site → docs/site/
```

Start with [`docs/src/index.md`](docs/src/index.md). The original vision, functional spec, and technical spec are in [`notes/`](notes/).

## Develop

```sh
make help            # every target, grouped and described
make frontend        # build TS/Vite UI → src/terminux/web/static
make frontend-dev    # live Vite dev server against a --no-window backend
make frontend-test   # vitest unit tests (fast, no browser)
make frontend-cov    # frontend coverage report
make test            # everything: vitest, then pytest unit/integration/e2e
make lint            # ruff + ty + pyrefly + mypy
make format
```

The e2e tier drives the served UI with a real browser (no pywebview); install it once with `uv run playwright install chromium`.

## Status: 0.11 preview

**Works today (0.11):** the workspaces sidebar (create / rename / reorder / close, working/ready dot) and tabs of real PTY shells that keep streaming in the background. Layout *and scrollback* come back after a restart, always with fresh shells. Remote mode (`--server` / `--connect`) reconnects automatically. The same `Ctrl+Shift` shortcuts work on all three platforms. Program-printed hyperlinks open, a watchdog diagnoses freezes, and standalone macOS and Linux bundles build with one command. On Windows 10 and 11, terminux runs PowerShell or `cmd` in its tabs and can also connect to a server on another machine.

**Not yet:** split panes, a standalone Windows bundle, multi-user accounts.

## Architecture in one breath

A Vite/TypeScript web UI (xterm.js for the terminals, Preact for the chrome around them) runs in a sandboxed pywebview window and talks to a loopback Starlette/uvicorn backend that owns the PTYs and streams raw bytes over per-terminal WebSockets. The frontend build output is committed to `src/terminux/web/static/`, so the Python package runs with no Node toolchain.

<div align="center">
<sub>terminux is built for people who keep too many terminals open. <a href="https://github.com/abilian/terminux">abilian/terminux</a></sub>
</div>
