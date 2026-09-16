"""Entrypoint: run the loopback server, then host it in a pywebview window.

``--no-window`` runs the server headless (browse to the printed URL) — used
for development and e2e tests, and a preview of the future "web mode".
"""

from __future__ import annotations

import argparse
import contextlib
import faulthandler
import json
import logging
import re
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlparse

import platformdirs
import uvicorn

from terminux.constants import DOCS_URL
from terminux.diagnostics import start_watchdog
from terminux.openurl import open_url_in_default_app
from terminux.server import auth as auth_mod
from terminux.server.asgi import AppController, build_app
from terminux.server.auth import SESSION_TOKEN

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PNG = _ASSETS_DIR / "icon.png"
ICON_ICNS = _ASSETS_DIR / "icon.icns"


def server_token_path() -> Path:
    """Where ``--server`` persists its auth token."""
    return Path(platformdirs.user_data_dir("terminux")) / "server.token"


if TYPE_CHECKING:
    from collections.abc import Callable

    from webview.menu import Menu, MenuAction, MenuSeparator

    MenuEntry = Menu | MenuAction | MenuSeparator


class _WebviewWindowLike(Protocol):
    def evaluate_js(self, script: str) -> object: ...


class _WebviewModuleLike(Protocol):
    def active_window(self) -> _WebviewWindowLike | None: ...


log = logging.getLogger(__name__)
HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


def _serve(server: uvicorn.Server) -> None:
    server.run()


def _wait_until_started(
    server: uvicorn.Server, thread: threading.Thread, bind: str
) -> None:
    """Block until uvicorn is accepting connections.

    If the server thread dies first (port already in use, bad bind
    address), exit with an error instead of spinning forever on a
    ``started`` flag that will never flip.
    """
    while not server.started:
        if not thread.is_alive():
            msg = f"server failed to start on {bind} — is the port already in use?"
            raise SystemExit(msg)
        time.sleep(0.02)


def _install_freeze_diagnostics() -> None:
    """Dump every thread's Python traceback to stderr on SIGUSR1 (or SIGINFO
    on BSDs / macOS, raised by Ctrl-T at a terminal). The next time the
    server wedges, ``kill -USR1 <pid>`` (or ``kill -INFO <pid>``) prints
    where every thread is parked — no debugger or py-spy install required.
    """
    faulthandler.enable()
    for name in ("SIGUSR1", "SIGINFO"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):
                faulthandler.register(sig, all_threads=True, chain=False)


def _configure_logging(*, debug: bool, trace: bool) -> None:
    """Set log levels per the ``--debug`` / ``--trace`` flags.

    Plain:    terminux.* at INFO,  uvicorn warnings only.
    --debug:  terminux.* at DEBUG, uvicorn at INFO with access logs.
    --trace:  everything (root) at DEBUG, uvicorn access logs, the
              I/O instrumentation also logs every operation (not just
              slow ones) by checking ``logging.DEBUG``.
    """
    fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
    datefmt = "%H:%M:%S"
    if trace:
        logging.basicConfig(level=logging.DEBUG, format=fmt, datefmt=datefmt)
    elif debug:
        logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt)
        logging.getLogger("terminux").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
        )
    # Every request URL carries ``?t=<token>``; without this, enabling
    # access logs (--debug/--trace) would write the token — persistent in
    # --server mode — into the logs on every line.
    logging.getLogger("uvicorn.access").addFilter(_RedactTokenFilter())


class _RedactTokenFilter(logging.Filter):
    """Scrub ``t=<token>`` from uvicorn access-log lines."""

    _TOKEN = re.compile(r"([?&]t=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._TOKEN.sub(r"\1***", a) if isinstance(a, str) else a
                for a in record.args
            )
        return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="terminux")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="run the server only (no desktop window)",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help=(
            "headless server mode. Same as --no-window but persists the auth "
            "token to ~/.../terminux/server.token so the URL is stable across "
            "restarts. Intended for remote use via `terminux --connect URL`."
        ),
    )
    parser.add_argument(
        "--connect",
        metavar="URL",
        default=None,
        help=(
            "open the desktop window pointed at a remote terminux server "
            "(e.g. http://localhost:8443/?t=abc-def-ghi). Skips spawning a "
            "local backend. Use an SSH tunnel for security."
        ),
    )
    parser.add_argument("--port", type=int, default=0, help="bind port (0 = ephemeral)")
    parser.add_argument(
        "--host",
        default=HOST,
        help="bind address (default 127.0.0.1; use 0.0.0.0 for container/web mode)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "verbose diagnostics: terminux.* loggers at DEBUG, uvicorn access "
            "logs, timestamps with ms precision"
        ),
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help=(
            "everything --debug enables plus: log every persisted state save, "
            "every scrollback read/write, every cwd lookup, and every PTY "
            "read/write (very chatty — only use when debugging a freeze)"
        ),
    )
    args = parser.parse_args()

    _configure_logging(debug=args.debug or args.trace, trace=args.trace)
    _install_freeze_diagnostics()

    # ----- client mode: no local backend, just a window onto a remote ---
    if args.connect:
        # No watchdog here: it monitors the local server's asyncio
        # heartbeat, and client mode runs no local server — arming it
        # would warn every 10 s about a loop that doesn't exist.
        _run_connected(args.connect, debug=args.debug or args.trace)
        return

    start_watchdog()

    # ----- server side: persist the token if we're in --server / --no-window
    headless = args.server or args.no_window
    if args.server:
        token = auth_mod.load_or_create_persistent_token(server_token_path())
    else:
        token = SESSION_TOKEN

    port = args.port or _free_port()
    app = build_app(persist=True)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=port,
        log_level="info" if (args.debug or args.trace) else "warning",
        access_log=args.debug or args.trace,
        ws="websockets-sansio",  # avoid the deprecated legacy websockets impl
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=_serve, args=(server,), daemon=True)
    thread.start()
    _wait_until_started(server, thread, f"{args.host}:{port}")

    shown_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host  # noqa: S104
    url = f"http://{shown_host}:{port}/?t={token}"
    log.info("terminux server ready at %s", url)
    if args.server:
        # Print a prominent banner with the connect URL so SSH-tunnel users
        # can copy it without grepping the log.
        sys.stderr.write(f"\nterminux server listening — connect with:\n  {url}\n\n")
        sys.stderr.flush()

    if headless:
        with contextlib.suppress(KeyboardInterrupt):
            thread.join()
        return

    _run_windowed(url, app.state.controller, server, debug=args.debug or args.trace)


def _drop_paths(event: dict[str, object]) -> list[str]:
    # WKWebView hides file paths from JS; pywebview injects the real path as
    # ``pywebviewFullPath`` only for a Python drop handler. ``event`` is
    # pywebview's loosely-typed JSON event dict (defensively re-checked).
    if not isinstance(event, dict):
        return []
    transfer = event.get("dataTransfer")
    files = (
        cast("dict[str, object]", transfer).get("files")
        if isinstance(transfer, dict)
        else None
    )
    paths: list[str] = []
    for f in files if isinstance(files, list) else []:
        if isinstance(f, dict):
            p = cast("dict[str, object]", f).get("pywebviewFullPath")
            if isinstance(p, str):
                paths.append(p)
    return paths


def _disable_macos_press_and_hold() -> None:
    """Turn off macOS's accent-picker popup so vim's hjkl key-repeat works.

    Without this, holding `j` or `k` for ~0.5 s pops up the accent
    selector instead of repeating the key — the WKWebView text-input
    layer hooks the same press-and-hold path Cocoa uses for regular text
    fields. Every native terminal app (iTerm2, Alacritty, kitty, Ghostty)
    flips this same default. The value persists for the host process's
    bundle identifier; the packaged .app keeps its own preferences and
    dev mode (`uv run terminux`) inherits Python's.
    """
    if sys.platform != "darwin":
        return
    try:
        # Foundation ships with PyObjC on macOS (pulled in by pywebview);
        # it's a dynamic Cocoa bridge that static checkers can't introspect.
        from Foundation import (  # noqa: PLC0415
            NSUserDefaults,  # ty: ignore[unresolved-import]  # pyrefly: ignore[missing-module-attribute]
        )
    except ImportError:
        log.warning("pyobjc Foundation not available; press-and-hold left enabled")
        return
    NSUserDefaults.standardUserDefaults().setBool_forKey_(
        False, "ApplePressAndHoldEnabled"
    )


def _set_macos_dock_icon() -> None:
    """Override the generic Python rocket in the dock when launched from the CLI.

    The packaged .app picks its icon up from ``Info.plist`` — but
    ``uv run terminux`` has no bundle, so AppKit falls back to the Python
    interpreter's icon. ``NSApplication.setApplicationIconImage_`` swaps it
    for the current process. Silently no-ops if PyObjC or the PNG is missing.
    """
    if sys.platform != "darwin" or not ICON_PNG.exists():
        return
    try:
        # AppKit ships with PyObjC on macOS — dynamic Cocoa bridge, opaque
        # to static checkers (same dance as the Foundation import above).
        from AppKit import (  # noqa: PLC0415
            NSApplication,  # ty: ignore[unresolved-import]  # pyrefly: ignore[missing-module-attribute]
            NSImage,  # ty: ignore[unresolved-import]  # pyrefly: ignore[missing-module-attribute]
        )
    except ImportError:
        return
    image = NSImage.alloc().initWithContentsOfFile_(str(ICON_PNG))
    if image is not None:
        NSApplication.sharedApplication().setApplicationIconImage_(image)


def _run_windowed(
    url: str, ctl: AppController, server: uvicorn.Server, *, debug: bool = False
) -> None:
    _disable_macos_press_and_hold()
    import webview  # noqa: PLC0415  (heavy GUI import; only when windowing)
    from webview.dom import DOMEventHandler  # noqa: PLC0415

    ui = ctl.state.ui
    window = webview.create_window(
        "terminux",
        url,
        width=ui.win_w,
        height=ui.win_h,
        x=ui.win_x,
        y=ui.win_y,
        # Catch Cmd/Ctrl+Q and the close button so a stray chord doesn't
        # nuke a workspace full of live shells without a prompt.
        confirm_close=True,
    )
    _set_macos_dock_icon()
    if window is None:
        msg = "failed to create application window"
        raise RuntimeError(msg)
    win = window  # non-None binding so closures don't see Optional

    def _on_resized(width: int, height: int) -> None:
        ui.win_w, ui.win_h = int(width), int(height)

    def _on_moved(x: int, y: int) -> None:
        ui.win_x, ui.win_y = int(x), int(y)

    # Geometry is tracked in memory and persisted by the shutdown save
    # (no per-event disk writes during a drag).
    win.events.resized += _on_resized
    win.events.moved += _on_moved

    def _on_drop(event: dict[str, object]) -> None:
        paths = _drop_paths(event)
        if paths:
            ctl.paste_paths(paths)

    def _register_drop() -> None:
        # Must run after the DOM is loaded; prevent_default stops the webview
        # from navigating to the dropped file.
        win.dom.document.on("drop", DOMEventHandler(_on_drop, prevent_default=True))

    def _shutdown() -> None:
        ctl.save()  # final persist on graceful close (technical spec §7)
        ctl.terminals.close_all()
        server.should_exit = True

    win.events.loaded += _register_drop
    win.events.closed += _shutdown
    # icon= is the GTK/QT taskbar/window icon (pywebview docs: "Supported
    # only on GTK/QT"); macOS uses _set_macos_dock_icon() above instead.
    # ``webview`` is a real module; the cast is purely to tell the static
    # checker that we'll only touch ``.active_window`` on it (which it
    # does have, but the module stubs don't declare).
    webview.start(
        menu=_build_menu(cast("_WebviewModuleLike", webview)),
        icon=str(ICON_PNG) if ICON_PNG.exists() else None,
        # --debug: enables pywebview's web inspector (right-click ->
        # Inspect Element) so frontend errors are debuggable in-window.
        debug=debug,
    )


# Default window geometry for ``--connect`` mode. No per-client persistence
# (intentional v1 scope): every connection opens at this size.
_CONNECT_DEFAULT_W = 1100
_CONNECT_DEFAULT_H = 720


def _post_paste_paths(server_url: str, paths: list[str]) -> None:
    """POST dropped file paths to a remote terminux via /api/paste-paths.

    Mirrors the local ``ctl.paste_paths`` call done in ``_run_windowed``,
    so file drag-and-drop behaves the same in ``--connect`` mode. The
    request includes the same auth token from the server URL.
    """
    parsed = urlparse(server_url)
    paste_url = f"{parsed.scheme}://{parsed.netloc}/api/paste-paths"
    if parsed.query:
        paste_url += f"?{parsed.query}"
    body = json.dumps({"paths": paths}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — fixed scheme/path, body is JSON
        paste_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2):  # noqa: S310
            pass
    except (urllib.error.URLError, OSError) as exc:
        log.warning("paste-paths POST to %s failed: %s", paste_url, exc)


def _run_connected(remote_url: str, *, debug: bool = False) -> None:
    """Open a pywebview window pointed at a remote terminux server.

    Skips spawning a local backend — the entire frontend (xterm.js, the
    sidebar, persistence) is served by the remote. The only local pieces
    are the window chrome, the native menu (whose actions route through
    the frontend's command bus via ``window.terminux.invoke``), and the
    file-drop handler (which POSTs to ``/api/paste-paths`` on the remote
    rather than calling a local controller).
    """
    _disable_macos_press_and_hold()
    import webview  # noqa: PLC0415  (heavy GUI import; only when windowing)
    from webview.dom import DOMEventHandler  # noqa: PLC0415

    window = webview.create_window(
        "terminux",
        remote_url,
        width=_CONNECT_DEFAULT_W,
        height=_CONNECT_DEFAULT_H,
        confirm_close=True,
    )
    _set_macos_dock_icon()
    if window is None:
        msg = "failed to create application window"
        raise RuntimeError(msg)
    win = window

    def _on_drop(event: dict[str, object]) -> None:
        paths = _drop_paths(event)
        if paths:
            _post_paste_paths(remote_url, paths)

    def _register_drop() -> None:
        win.dom.document.on("drop", DOMEventHandler(_on_drop, prevent_default=True))

    win.events.loaded += _register_drop
    # No close handler beyond pywebview's default — the remote server keeps
    # running, and there's no local controller to flush.

    webview.start(
        menu=_build_menu(cast("_WebviewModuleLike", webview)),
        icon=str(ICON_PNG) if ICON_PNG.exists() else None,
        # --debug: enables pywebview's web inspector (right-click ->
        # Inspect Element) so frontend errors are debuggable in-window.
        debug=debug,
    )


def _build_menu(webview_mod: _WebviewModuleLike) -> list[Menu]:
    """Build the native application menu — same set of verbs the keyboard
    chords and the command palette dispatch through, so the menu is just
    another input surface on the shared command bus.

    Each ``MenuAction`` callback ``evaluate_js``s into
    ``window.terminux.invoke('<id>')`` on the active window; URL items
    (Help → Documentation) bypass the bus and shell out via
    ``open_url_in_default_app`` since URL launching is Python-native.
    """
    # Import here so unit tests that exercise _build_menu without a real
    # webview can stub the module via the argument.
    from webview.menu import Menu, MenuAction, MenuSeparator  # noqa: PLC0415

    def _cmd(command_id: str) -> Callable[[], None]:
        js = f"window.terminux?.invoke({json.dumps(command_id)})"

        def callback() -> None:
            win = webview_mod.active_window()
            if win is not None:
                win.evaluate_js(js)

        return callback

    def _url(target: str) -> Callable[[], None]:
        def callback() -> None:
            open_url_in_default_app(target)

        return callback

    workspace_items: list[MenuEntry] = [
        MenuAction("Next Workspace", _cmd("workspace.next")),
        MenuAction("Previous Workspace", _cmd("workspace.prev")),
        MenuSeparator(),
    ]
    workspace_items.extend(
        MenuAction(f"Workspace {i}", _cmd(f"workspace.jump.{i}")) for i in range(1, 10)
    )
    workspace_items.extend([
        MenuSeparator(),
        MenuAction("Sort by Activity", _cmd("workspace.reorder-by-activity")),
    ])

    return [
        Menu(
            "File",
            [
                MenuAction("New Workspace", _cmd("workspace.new")),
                MenuAction("New Tab", _cmd("tab.new")),
                MenuSeparator(),
                MenuAction("Close Tab", _cmd("tab.close")),
                MenuAction("Close Workspace", _cmd("workspace.close")),
            ],
        ),
        Menu(
            "View",
            [
                MenuAction("Quick Switcher", _cmd("palette.quick")),
                MenuAction("Command Palette", _cmd("palette.command")),
                MenuSeparator(),
                MenuAction("Find…", _cmd("view.find")),
                MenuAction("Usage Stats", _cmd("view.stats")),
                MenuSeparator(),
                MenuAction("Zoom In", _cmd("view.zoom.in")),
                MenuAction("Zoom Out", _cmd("view.zoom.out")),
                MenuAction("Reset Zoom", _cmd("view.zoom.reset")),
                MenuSeparator(),
                MenuAction("Toggle Sidebar", _cmd("view.sidebar.toggle")),
                MenuSeparator(),
                MenuAction(
                    "Toggle Auto-Copy on Selection",
                    _cmd("view.copy-on-select.toggle"),
                ),
                MenuAction(
                    "Toggle Scrollback Persistence",
                    _cmd("view.scrollback-persist.toggle"),
                ),
            ],
        ),
        Menu("Workspace", workspace_items),
        Menu("Help", [MenuAction("Documentation", _url(DOCS_URL))]),
    ]


if __name__ == "__main__":
    main()
