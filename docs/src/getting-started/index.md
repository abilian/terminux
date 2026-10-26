# Installation

## Install from PyPI

terminux runs on macOS 12 (Monterey) or later, Linux, and Windows 10/11, with Python 3.12 or later. On macOS 11 (Big Sur), installing or upgrading gets you 0.10.1, the last version that runs there. With [`uv`](https://docs.astral.sh/uv/):

```sh
uvx terminux                  # try it without installing
uv tool install terminux      # install it
uv tool upgrade terminux      # upgrade later
```

### On Linux

The window needs GTK and WebKitGTK, with their Python bindings (PyGObject), from your distribution: PyPI can't provide them. Install them, then install terminux with `pipx`, which can let terminux see them (`uv tool` and `uvx` can't):

=== "Fedora"

    ```sh
    sudo dnf install python3-gobject gtk3 webkit2gtk4.1
    ```

=== "Debian, Ubuntu"

    ```sh
    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
    ```

=== "Arch"

    ```sh
    sudo pacman -S python-gobject webkit2gtk-4.1
    ```

```sh
pipx install --python /usr/bin/python3 --system-site-packages terminux
```

If something is missing, `terminux` says what to install and exits. Without GTK, `terminux --no-window` still works: it serves the same interface to any browser, at the URL it prints.

Without a display (in an SSH session, say), there is no window to open: run `terminux --no-window`, or `terminux --server -d` and connect to it from a machine with a display, as [Remote access](../guides/remote.md) describes. terminux says so if you forget.

## Requirements for running from source

- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/) for the Python side.
- **Node.js**: only to *build* the frontend. The build output is committed to
  `src/terminux/web/static/`, so running from source does **not** require Node
  unless you change the frontend.

## Run from source

```sh
uv sync                      # install Python dependencies
make frontend                # build the web UI (needs Node; first run only)
uv run terminux              # desktop window (pywebview)
uv run terminux -d           # same, in the background (macOS, Linux)
```

To run the backend without the desktop shell (the dev/test path and a preview
of the future *web mode*), use:

```sh
uv run terminux --no-window  # server only; open the printed URL in a browser
```

The printed URL contains a per-session token
(`http://127.0.0.1:<port>/?t=<token>`). That token is the only authentication,
so keep the URL private if you ever bind beyond loopback with `--host`.

## Packaged app

terminux can be bundled into a self-contained desktop app that needs neither
Python nor Node to run.

=== "Linux"

    ```sh
    make build-linux     # -> dist/linux/terminux/terminux (PyInstaller onedir)
    make docker-run      # run the same image in web mode on :8000
    ```

    Built in a container (PyInstaller can't cross-compile). Runtime host
    needs `libgtk-3` and `libwebkit2gtk-4.1`.

=== "macOS"

    ```sh
    make build-macos
    open dist/terminux.app
    ```

    The bundle embeds the Python backend, the built web UI, and pywebview's
    WKWebView backend.

See [Packaging & distribution](../developers/packaging.md) for signing, Gatekeeper, X11, and
architecture details.

## First steps in the app

1. terminux opens with a default workspace and one terminal tab.
2. Press ++cmd+n++ / ++ctrl+n++ to create a workspace, ++cmd+t++ / ++ctrl+t++
   for a new tab.
3. `cd` somewhere: the workspace name follows the **first tab's** working
   directory until you pin a name by renaming it (pinned names persist
   across restarts).
4. Quit and relaunch: your workspaces and tabs come back, each shell respawned
   in the directory it was in at exit.

Continue with [Workspaces & tabs](../guides/workspaces-and-tabs.md).
