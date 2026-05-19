# terminux

A cross-platform desktop terminal with a Workspaces sidebar and tabbed
terminals. Workspaces and their tabs persist across restarts.

Inspired by cmux (workspace UX) and terax (architecture), implemented in
Python: a Vite/TypeScript xterm.js web UI hosted in a pywebview window,
talking to a loopback Starlette/uvicorn backend that owns the PTYs. See
`notes/` for the vision, functional spec, and technical spec.

The frontend lives in `frontend/` (TypeScript modules, Vite). Its build
output is committed to `src/terminux/web/static/` so the Python package
runs without a Node toolchain; rebuild it with `make frontend`.

## Run

```sh
uv sync
make frontend                # build the web UI (needs Node; first run only)
uv run terminux              # desktop window (pywebview)
uv run terminux --no-window  # server only; open the printed URL in a browser
```

`--no-window` is the dev/test path and a preview of the future "web mode".

## Package (macOS .app)

```sh
make app           # builds the frontend, then dist/terminux.app (PyInstaller)
open dist/terminux.app
```

The bundle embeds the Python backend, the built web UI, and pywebview's
WKWebView backend — no Python/Node needed to run it. Notes:

- Built for the host architecture (arm64 here). A universal2 binary needs
  a universal Python; not configured.
- The app is **ad-hoc signed only**. On another Mac, Gatekeeper will block
  it until right-click → Open (or it's signed with a Developer ID and
  notarized — out of scope for the prototype).
- `dist/` and `build/` are gitignored; the `.app` is a build artifact.

## Package (Linux, via Docker)

PyInstaller can't cross-compile, so the Linux bundle is built in a
container (Ubuntu 24.04 + GTK3/WebKit2GTK + Python 3.12):

```sh
make linux         # -> dist/linux/terminux/terminux (PyInstaller onedir)
make docker-run    # run the same image in web mode on :8000
```

- **Web mode is the container-native use.** `make docker-run` serves the
  UI headlessly; open the `http://127.0.0.1:8000/?t=<token>` URL from the
  container log in a browser. The session token is the only auth when
  bound beyond loopback (`--host 0.0.0.0`) — keep it private.
- **The desktop GUI in a container needs a display.** Run the bundled
  binary natively on a Linux desktop (needs `libgtk-3` + `libwebkit2gtk-4.1`),
  or pass X11 through:
  ```sh
  docker run --rm -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix terminux:bundle \
    /app/dist/terminux/terminux
  ```
- The bundle's architecture matches the Docker host (arm64 here). For
  x86_64, build with `docker build --platform linux/amd64 …`.
- Unsigned; `dist/`/`build/` are gitignored build artifacts.

## Status — v1 prototype

Works: workspaces sidebar (create/rename/reorder/close, auto status dot),
tabs with multiple live terminals, real PTY shells over a per-terminal
WebSocket, background tabs keep streaming, structure persisted to disk
(fresh shells on restart), per-session loopback token.

Not yet: split panes, client/server detach, packaging, Windows PTY,
scrollback persistence — see `notes/technical-spec.md` §11–§14.

## Develop

```sh
make frontend        # build TS/Vite UI → src/terminux/web/static
make frontend-test   # vitest unit tests (pure TS logic)
make test            # pytest: a_unit, b_integration, c_e2e (Playwright)
make lint            # ruff + ty + pyrefly + mypy
make format
cd frontend && npm run typecheck   # frontend type-check (tsc)
```

The `c_e2e` tier drives the served UI with a real browser (no pywebview).
It needs the Playwright browser once: `uv run playwright install chromium`.
