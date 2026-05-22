# Getting started

## Requirements

- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/) for the Python side.
- **Node.js** — only to *build* the frontend. The build output is committed to
  `src/terminux/web/static/`, so running from source does **not** require Node
  unless you change the frontend.

## Run from source

```sh
uv sync                      # install Python dependencies
make frontend                # build the web UI (needs Node; first run only)
uv run terminux              # desktop window (pywebview)
```

To run the backend without the desktop shell — the dev/test path and a preview
of the future *web mode* — use:

```sh
uv run terminux --no-window  # server only; open the printed URL in a browser
```

The printed URL contains a per-session token
(`http://127.0.0.1:<port>/?t=<token>`). That token is the only authentication,
so keep the URL private if you ever bind beyond loopback with `--host`.

## Packaged app

terminux can be bundled into a self-contained desktop app — no Python or Node
needed to run it.

=== "Linux"

    ```sh
    make linux           # -> dist/linux/terminux/terminux (PyInstaller onedir)
    make docker-run      # run the same image in web mode on :8000
    ```

    Built in a container (PyInstaller can't cross-compile). Runtime host
    needs `libgtk-3` and `libwebkit2gtk-4.1`.

=== "macOS"

    ```sh
    make app
    open dist/terminux.app
    ```

    The bundle embeds the Python backend, the built web UI, and pywebview's
    WKWebView backend.

See [Packaging & distribution](packaging.md) for signing, Gatekeeper, X11, and
architecture details.

## First steps in the app

1. terminux opens with a default workspace and one terminal tab.
2. Press ++cmd+n++ / ++ctrl+n++ to create a workspace, ++cmd+t++ / ++ctrl+t++
   for a new tab.
3. `cd` somewhere — the workspace name follows the **first tab's** working
   directory until you pin a name by renaming it (pinned names survive
   restarts).
4. Quit and relaunch: your workspaces and tabs come back, each shell respawned
   in the directory it was in at exit.

Continue with [Workspaces & tabs](workspaces-and-tabs.md).
