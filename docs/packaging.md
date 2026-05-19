# Packaging & distribution

terminux bundles into a self-contained desktop app — no Python or Node required
to run it. Bundles are built with PyInstaller; `dist/` and `build/` are
gitignored build artifacts.

## macOS (`.app`)

```sh
make app           # builds the frontend, then dist/terminux.app
open dist/terminux.app
```

The bundle embeds the Python backend, the built web UI, and pywebview's
WKWebView backend.

!!! warning "Architecture & signing"
    - Built for the **host architecture** (arm64 on Apple Silicon). A
      `universal2` binary needs a universal Python and is not configured.
    - The app is **ad-hoc signed only**. On another Mac, Gatekeeper blocks it
      until right-click → **Open** — or until it is signed with a Developer ID
      and notarized (out of scope for the prototype).

## Linux (via Docker)

PyInstaller can't cross-compile, so the Linux bundle is built in a container
(Ubuntu 24.04 + GTK3/WebKit2GTK + Python 3.12):

```sh
make linux         # -> dist/linux/terminux/terminux (PyInstaller onedir)
make docker-run    # run the same image in web mode on :8000
```

### Web mode (container-native)

`make docker-run` serves the UI headlessly. Open the
`http://127.0.0.1:8000/?t=<token>` URL from the container log in a browser.

!!! danger "The session token is the only auth"
    When bound beyond loopback (`--host 0.0.0.0`), the per-session token is the
    only authentication. Keep the URL private.

### Desktop GUI in a container

The desktop GUI needs a display. Either run the bundled binary natively on a
Linux desktop (needs `libgtk-3` + `libwebkit2gtk-4.1`), or pass X11 through:

```sh
docker run --rm -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix terminux:bundle \
  /app/dist/terminux/terminux
```

The bundle's architecture matches the Docker host (arm64 here). For x86_64,
build with `docker build --platform linux/amd64 …`. The Linux bundle is
unsigned.

## Windows

Not yet — the Windows PTY backend is on the roadmap. See the [FAQ](faq.md).
