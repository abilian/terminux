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

## Troubleshooting on macOS

### "Operation not permitted" in your shell

If shells inside terminux start showing errors like:

```
/bin/bash: /opt/homebrew/bin/brew: Operation not permitted
sh: /opt/homebrew/opt/nvm/nvm.sh: Operation not permitted
dyld: Library not loaded: /opt/homebrew/opt/pcre2/lib/libpcre2-8.0.dylib
  Reason: tried: '…' (file system sandbox blocked open())
```

…this is **macOS TCC** (the "Files and Folders" / "Full Disk Access" privacy
controls) blocking the spawned shell from reading files on a path the
parent process isn't allowed to touch — most commonly a **removable volume**
(an external SSD where Homebrew, `nvm`, or similar has been relocated).

The phrase `file system sandbox blocked open()` is the giveaway: it comes
from macOS's `sandboxd`, not a chmod or ACL.

#### Why it can appear mid-session

TCC decisions are made at *access time*, not when the process starts. The
first shells often don't touch the protected location — your prompt, `cd`,
and basic builtins stay on the boot drive. The block kicks in only when
something later re-sources `.profile` / `.zshrc` or a new tab spawns a fresh
shell that `dlopen()`s a library from the restricted path.

#### Fix

1. Identify the **TCC-responsible parent** of the shells. Under pywebview
   it's typically `python3.12` from your `.venv/bin/`, or `uv` if you
   launched via `uv run terminux`, or `dist/terminux.app/Contents/MacOS/terminux`
   if you ran the packaged bundle. From a working terminal (e.g. iTerm2):
   ```sh
   ps -o pid,ppid,command -p $(pgrep -f terminux)
   ```
2. Open **System Settings → Privacy & Security**, then either:
    - **Files and Folders → Removable Volumes** — grant access to the
      specific external drive (narrower scope), *or*
    - **Full Disk Access** — add the executable (broader; needed if you
      rely on protected boot-drive locations too).
3. Add the executable identified in step 1.
4. **Restart terminux.** macOS only re-evaluates TCC scope at process
   start.

If you're running from the `.app` bundle, grant FDA to the bundle itself,
not the embedded Python.

#### Quick check

You can confirm the diagnosis without changing settings by spawning a
working terminal (iTerm2 / Terminal.app with FDA) and seeing whether
`brew --version` succeeds there but fails in terminux. Same shell, same
PATH, different TCC scope.
