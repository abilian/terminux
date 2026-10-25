"""Entrypoint: run the loopback server, then host it in a pywebview window.

``--no-window`` runs the server headless (browse to the printed URL) — used
for development and e2e tests, and a preview of the future "web mode".
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import faulthandler
import json
import logging
import os
import re
import signal
import socket
import subprocess  # noqa: S404 — argv form only, no shell: relaunches this program
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Protocol, cast
from urllib.parse import urlparse

import platformdirs
import uvicorn

from terminux import clipboard, gui_prereq
from terminux.constants import DOCS_URL
from terminux.core import persistence
from terminux.core.model import UiPrefs
from terminux.diagnostics import start_watchdog
from terminux.openurl import open_url_in_default_app
from terminux.server import auth as auth_mod
from terminux.server.api import ui_updates
from terminux.server.asgi import build_app
from terminux.server.auth import LOOPBACK_BINDS, SESSION_TOKEN

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PNG = _ASSETS_DIR / "icon.png"
ICON_ICNS = _ASSETS_DIR / "icon.icns"
# pywebview's window icon: WinForms needs a .ico (System.Drawing.Icon
# rejects a PNG and kills the UI thread); GTK/Qt take the PNG; macOS
# ignores it (see _set_macos_dock_icon).
WINDOW_ICON = _ASSETS_DIR / ("icon.ico" if sys.platform == "win32" else "icon.png")


def server_token_path() -> Path:
    """Where ``--server`` persists its auth token."""
    return persistence.data_dir() / "server.token"


if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from starlette.applications import Starlette
    from webview import Window
    from webview.menu import Menu, MenuAction, MenuSeparator

    from terminux.server.controller import AppController

    MenuEntry = Menu | MenuAction | MenuSeparator


class _WebviewWindowLike(Protocol):
    def evaluate_js(self, script: str) -> object: ...
    def toggle_fullscreen(self) -> None: ...


class _WebviewModuleLike(Protocol):
    def active_window(self) -> _WebviewWindowLike | None: ...


log = logging.getLogger(__name__)
HOST = "127.0.0.1"
# --daemon's default port: the URL must survive restarts (the token does
# too), and the remote guide's examples already use it.
DAEMON_PORT = 8443
_WILDCARD_BINDS = frozenset({"0.0.0.0", "::"})  # noqa: S104  (names, not binds)


def _daemon_log_path() -> Path:
    return platformdirs.user_log_path("terminux", appauthor=False) / "terminux.log"


def _daemon_pid_path() -> Path:
    return platformdirs.user_state_path("terminux", appauthor=False) / "terminux.pid"


def _running_daemon_pid(pid_path: Path) -> int | None:
    """The PID recorded in ``pid_path`` if that process is still alive. A
    file left behind by a crash or ``kill -9`` names a dead process."""
    try:
        pid = int(pid_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return pid if _alive(pid) else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # another user's process: the PID was reused
        return False
    return True


def _connect_url(public_host: str | None, bind: str, port: int, token: str) -> str:
    """The URL to print. ``--public-host`` wins; otherwise a wildcard bind
    names this machine (routable on the network), a loopback bind keeps the
    loopback address (reach it through an SSH tunnel)."""
    if public_host:
        host = public_host
    elif bind in _WILDCARD_BINDS:
        host = socket.getfqdn()
    else:
        host = bind
    if ":" in host:  # a bare IPv6 address needs brackets in a URL
        host = f"[{host}]"
    return f"http://{host}:{port}/?t={token}"


def _banner(url: str, bind: str) -> str:
    text = f"\nterminux server listening — connect with:\n  {url}\n"
    if bind in LOOPBACK_BINDS:
        text += (
            f"It listens on {bind} only: from another machine, go through an SSH "
            "tunnel, or start it with --host 0.0.0.0.\n"
        )
    return text + "\n"


# Set in the background process's environment: the write end of the pipe
# its launcher waits on.
_READY_FD_ENV = "TERMINUX_DAEMON_READY_FD"


def _daemonize(banner: str) -> Callable[[str | None], None]:
    """Go to the background and return the background process's readiness
    callback.

    The launcher (the process the user started) runs the same command again
    as a new process in its own session, detached from the terminal, and
    waits on a pipe until that process is accepting connections (or failed
    to bind). It prints the banner or the error and exits; the shell gets
    its prompt back only once the URL works. A plain fork would be lighter,
    but on macOS a forked child that doesn't exec can't reach the system's
    XPC services, and its window stays blank.

    The background process logs to ``_daemon_log_path()``, stdout and stderr
    included (fault dumps, uncaught tracebacks). Its PID goes to
    ``_daemon_pid_path()``, removed when it stops; a second daemon refuses
    to start while the first is alive, since both would write the same
    saved state.
    """
    ready_fd = os.environ.pop(_READY_FD_ENV, None)  # shells mustn't inherit it
    if ready_fd is None:
        _launch_daemon(banner)  # exits
    write_end = int(ready_fd)
    pid_path = _daemon_pid_path()

    def notify_ready(error: str | None) -> None:
        if error is None:
            pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
            # SIGTERM stops the server gracefully (``_serve_until_stopped``,
            # ``_close_on_sigterm``), so the interpreter exits normally and
            # runs this.
            atexit.register(pid_path.unlink, missing_ok=True)
        message = error if error is not None else f"ok {os.getpid()}"
        os.write(write_end, message.encode())
        os.close(write_end)

    return notify_ready


def _launch_daemon(banner: str) -> NoReturn:
    log_path = _daemon_log_path()
    pid_path = _daemon_pid_path()
    running = _running_daemon_pid(pid_path)
    if running is not None:
        msg = (
            f"terminux daemon already running (pid {running}); "
            "stop it with terminux --stop"
        )
        raise SystemExit(msg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    frozen = getattr(sys, "frozen", False)  # a PyInstaller bundle
    command = [sys.executable] if frozen else [sys.executable, "-m", "terminux"]
    read_end, write_end = os.pipe()
    logfile = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    subprocess.Popen(  # noqa: S603 — this program's own argv, no shell
        [*command, *sys.argv[1:]],
        stdin=subprocess.DEVNULL,
        stdout=logfile,
        stderr=logfile,
        cwd="/",
        env={**os.environ, _READY_FD_ENV: str(write_end)},
        pass_fds=(write_end,),
        start_new_session=True,
    )
    os.close(logfile)
    os.close(write_end)
    with os.fdopen(read_end, "rb") as pipe:
        report = pipe.read().decode()
    if not report.startswith("ok "):
        raise SystemExit(
            report or f"terminux daemon died while starting; see {log_path}"
        )
    pid = report.split()[1]
    sys.stderr.write(
        f"{banner}Running in the background (pid {pid}).\n"
        f"  log: {log_path}\n  pid file: {pid_path}\n"
    )
    raise SystemExit(0)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


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

    Every mode stamps a full date: a long-running instance's log spans
    days, and a stall can only be explained by what happened when.
    --debug and --trace add milliseconds.
    """
    datefmt = "%Y-%m-%d %H:%M:%S"
    precise = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s"
    if trace:
        logging.basicConfig(level=logging.DEBUG, format=precise, datefmt=datefmt)
    elif debug:
        logging.basicConfig(level=logging.INFO, format=precise, datefmt=datefmt)
        logging.getLogger("terminux").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt=datefmt,
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


def _parse_args() -> argparse.Namespace:
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
    parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help=(
            "go to the background once the server is up, after printing the "
            "connect URL; the window opens as usual (with --server, there is "
            f"none). Logs go to {_daemon_log_path()}. Not available on Windows."
        ),
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop the terminux started by --daemon, and wait until it is gone",
    )
    parser.add_argument(
        "--public-host",
        metavar="NAME",
        default=None,
        help=(
            "hostname or address to print in the connect URL (with --server or "
            "--daemon), so it is routable from other machines"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"bind port (default: {DAEMON_PORT} with --daemon, else ephemeral)",
    )
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
    if args.daemon and sys.platform == "win32":
        parser.error("--daemon is not available on Windows")
    return args


def _stop_daemon() -> None:
    """SIGTERM the daemon named in the PID file and wait until it's gone:
    it saves its state and closes its shells first (``timeout_graceful_
    shutdown`` bounds that), then removes the file."""
    pid_path = _daemon_pid_path()
    pid = _running_daemon_pid(pid_path)
    if pid is None:
        msg = "no terminux daemon is running"
        raise SystemExit(msg)
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while _alive(pid):
        if time.monotonic() > deadline:
            msg = f"terminux daemon (pid {pid}) did not stop"
            raise SystemExit(msg)
        time.sleep(0.05)
    sys.stderr.write(f"terminux daemon stopped (pid {pid})\n")


def main() -> None:
    args = _parse_args()
    if args.stop:
        _stop_daemon()
        return
    headless = args.server or args.no_window
    verbose = args.debug or args.trace
    # Before anything starts (and before --daemon forks), so a machine that
    # can't open the window says what to install instead of a traceback.
    if (args.connect or not headless) and (
        problem := gui_prereq.explain_why_no_window()
    ):
        raise SystemExit(problem)

    if args.connect:
        # Client mode: no local backend, just a window onto a remote.
        _configure_logging(debug=verbose, trace=args.trace)
        _install_freeze_diagnostics()
        # No watchdog here: it monitors the local server's asyncio
        # heartbeat, and client mode runs no local server — arming it
        # would warn every 10 s about a loop that doesn't exist.
        _run_connected(args.connect, debug=verbose)
        return
    _run_local(args, headless=headless, verbose=verbose)


def _run_local(args: argparse.Namespace, *, headless: bool, verbose: bool) -> None:
    """Run the local server, then the window unless ``headless``."""
    # The daemon picks its port and token before forking, so the parent can
    # print the URL; everything else (logging, threads, the window) starts in
    # the child. The printed URL outlives a restart, as with --server.
    persistent = args.server or args.daemon
    if persistent:
        token = auth_mod.load_or_create_persistent_token(server_token_path())
    else:
        token = SESSION_TOKEN
    port = args.port or (DAEMON_PORT if args.daemon else _free_port())
    url = _connect_url(args.public_host, args.host, port, token)
    notify_ready = _daemonize(_banner(url, args.host)) if args.daemon else None

    _configure_logging(debug=verbose, trace=args.trace)
    _install_freeze_diagnostics()
    start_watchdog()

    app = build_app(persist=True)
    # Tell the app how it was bound, so "Show remote connection URL" can
    # say whether a tunnel is needed and whether the URL outlives the run.
    app.state.bind_host = args.host
    app.state.bind_port = port
    app.state.token_persistent = persistent
    app.state.public_host = args.public_host
    server, thread = _start_server(app, args.host, port, verbose=verbose)
    try:
        _wait_until_started(server, thread, f"{args.host}:{port}")
    except SystemExit as exc:
        if notify_ready is not None:
            notify_ready(str(exc))
        raise

    log.info("terminux server ready at %s", url)
    if notify_ready is not None:
        notify_ready(None)  # the parent prints the banner and exits
    elif args.server:
        # A prominent banner, so the URL can be copied without grepping the log.
        sys.stderr.write(_banner(url, args.host))
        sys.stderr.flush()

    if headless:
        _serve_until_stopped(server, thread)
        return

    # The local window always goes through loopback, whatever is printed.
    local = "127.0.0.1" if args.host in _WILDCARD_BINDS else args.host
    local_url = _connect_url(local, args.host, port, token)
    _run_windowed(local_url, app.state.controller, server, debug=verbose)
    thread.join(timeout=5)  # let the lifespan shutdown save and close


def _start_server(
    app: Starlette, host: str, port: int, *, verbose: bool
) -> tuple[uvicorn.Server, threading.Thread]:
    """Start uvicorn on a thread; the caller waits for it to be up."""
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info" if verbose else "warning",
        access_log=verbose,
        ws="websockets-sansio",  # avoid the deprecated legacy websockets impl
        # A stop waits for open connections (websockets) to close; don't
        # let a stuck one keep the process, and ``--stop``, waiting.
        timeout_graceful_shutdown=3,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


def _serve_until_stopped(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Block until the server stops. SIGTERM (``terminux --stop``, systemd)
    and Ctrl-C ask uvicorn to exit gracefully, so the app's lifespan
    shutdown gets to save the state and close the shells."""

    def stop(_signum: int, _frame: object) -> None:
        server.should_exit = True

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
            thread.join()
    finally:
        signal.signal(signal.SIGTERM, previous)


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


def _name_macos_app() -> None:
    """Call the app "terminux" in the menu bar and its app menu. Launched
    from a console script, the process has no bundle of its own, so macOS
    takes the interpreter's name ("Python" for a framework build). The
    info dictionary is mutable in place; pywebview edits it the same way,
    and reads ``CFBundleName`` from it when it builds the app menu."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import (  # noqa: PLC0415
            NSBundle,  # ty: ignore[unresolved-import]  # pyrefly: ignore[missing-module-attribute]
        )
    except ImportError:
        return
    bundle = NSBundle.mainBundle()
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    info["CFBundleName"] = "terminux"


class _KeyEvent(Protocol):
    def modifierFlags(self) -> int: ...  # noqa: N802  (Cocoa method)
    def keyCode(self) -> int: ...  # noqa: N802


class _Pastable(Protocol):
    def paste_(self, sender: object) -> None: ...


def _paste_on_ctrl_shift_v(cocoa: ModuleType) -> None:
    """Make Ctrl+Shift+V paste on macOS, as on Linux and Windows.

    WKWebView won't let the page read the clipboard (it pops a "Paste"
    bubble at best), so the chord runs the native paste, as pywebview's
    ``keyDown_`` does for Cmd+V. The page never sees the key.
    """
    shift, ctrl, option, cmd = (1 << 17, 1 << 18, 1 << 19, 1 << 20)  # NSEvent flags
    key_v = 9  # kVK_ANSI_V: the physical key, as the page's ``e.code``
    host = cocoa.BrowserView.WebKitHost
    key_down = host.keyDown_

    def keyDown_(self: _Pastable, event: _KeyEvent) -> None:  # noqa: N802  (Cocoa selector)
        mods = event.modifierFlags() & (shift | ctrl | option | cmd)
        if mods == ctrl | shift and event.keyCode() == key_v:
            self.paste_(self)
            return
        key_down(self, event)

    host.keyDown_ = keyDown_


def _disable_macos_app_nap() -> object | None:
    """Keep macOS from App-Napping terminux while its window is hidden.

    App Nap stretches the timers and lowers the CPU priority of an app
    whose window is covered or hidden, or of every app while the display
    sleeps with the Mac awake. A terminal must keep draining its hidden
    tabs, firing the "ready" signal, and answering websocket keepalives.

    Returns the activity token, which the caller must hold for as long as
    the window lives: releasing it ends the opt-out. The option still
    *allows idle system sleep*, so terminux never keeps the Mac awake.
    """
    if sys.platform != "darwin":
        return None
    try:
        from Foundation import (  # noqa: PLC0415
            NSActivityUserInitiatedAllowingIdleSystemSleep,  # ty: ignore[unresolved-import]  # pyrefly: ignore[missing-module-attribute]
            NSProcessInfo,  # ty: ignore[unresolved-import]  # pyrefly: ignore[missing-module-attribute]
        )
    except ImportError:
        log.warning("pyobjc Foundation not available; App Nap left enabled")
        return None
    return cast(
        "object",
        NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiatedAllowingIdleSystemSleep,
            "terminux streams live terminals, including hidden tabs",
        ),
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


def _open_window(
    url: str,
    *,
    geometry: tuple[int, int, int | None, int | None],
    on_paths: Callable[[list[str]], None],
    on_window: Callable[[Window], None] | None = None,
    debug: bool = False,
) -> None:
    """Open the terminux window on ``url`` at ``geometry`` (width, height,
    x, y) and run the GUI loop until it closes. Dropped files go to
    ``on_paths``; ``on_window`` hooks more events before the loop starts."""
    _name_macos_app()  # before pywebview reads the name
    _disable_macos_press_and_hold()
    _app_nap = _disable_macos_app_nap()  # held: releasing it re-enables App Nap
    import webview  # noqa: PLC0415  (heavy GUI import; only when windowing)

    if sys.platform == "darwin":
        from webview.platforms import cocoa  # noqa: PLC0415

        # pywebview adds a View menu of its own, holding only "Enter Full
        # Screen", next to ours; ours carries that item (``_build_menu``).
        # No setting turns off that menu alone, hence the private patch.
        cocoa.BrowserView._add_view_menu = lambda *_a, **_k: None  # type: ignore[method-assign]  # noqa: SLF001
        _paste_on_ctrl_shift_v(cocoa)
    from webview.dom import DOMEventHandler  # noqa: PLC0415

    window = webview.create_window(
        "terminux",
        url,
        width=geometry[0],
        height=geometry[1],
        x=geometry[2],
        y=geometry[3],
        # Catch Cmd/Ctrl+Q and the close button so a stray chord doesn't
        # nuke a workspace full of live shells without a prompt.
        confirm_close=True,
    )
    _set_macos_dock_icon()
    if window is None:
        msg = "failed to create application window"
        raise RuntimeError(msg)
    win = window  # non-None binding so closures don't see Optional

    def _on_drop(event: dict[str, object]) -> None:
        paths = _drop_paths(event)
        if paths:
            on_paths(paths)

    def _register_drop() -> None:
        # Must run after the DOM is loaded; prevent_default stops the webview
        # from navigating to the dropped file.
        win.dom.document.on("drop", DOMEventHandler(_on_drop, prevent_default=True))

    win.events.loaded += _register_drop
    if on_window is not None:
        on_window(win)
    # icon= is the GTK/QT taskbar/window icon (pywebview docs: "Supported
    # only on GTK/QT"); macOS uses _set_macos_dock_icon() above instead.
    # ``webview`` is a real module; the cast is purely to tell the static
    # checker that we'll only touch ``.active_window`` on it (which it
    # does have, but the module stubs don't declare).
    webview.start(
        menu=_build_menu(cast("_WebviewModuleLike", webview)),
        icon=str(WINDOW_ICON),
        # --debug: enables pywebview's web inspector (right-click ->
        # Inspect Element) so frontend errors are debuggable in-window.
        debug=debug,
    )


def _run_windowed(
    url: str, ctl: AppController, server: uvicorn.Server, *, debug: bool = False
) -> None:
    ui = ctl.state.ui

    def _remember(**geometry: int) -> None:
        # Same clamps as PATCH /api/ui; the GUI thread takes the state lock
        # like every other writer.
        updates = ui_updates(geometry)
        with ctl.lock:
            for k, v in updates.items():
                setattr(ui, k, v)

    def _track(win: Window) -> None:
        def _on_resized(width: int, height: int) -> None:
            _remember(win_w=width, win_h=height)

        def _on_moved(x: int, y: int) -> None:
            _remember(win_x=x, win_y=y)

        def _shutdown() -> None:
            # The final save and closing the shells happen in the app's
            # lifespan shutdown, on the loop (technical spec §7).
            server.should_exit = True

        # Geometry is tracked in memory and persisted by the shutdown save
        # (no per-event disk writes during a drag).
        win.events.resized += _on_resized
        win.events.moved += _on_moved
        win.events.closed += _shutdown
        if sys.platform != "win32":
            _close_on_sigterm(win)

    _open_window(
        url,
        geometry=(ui.win_w, ui.win_h, ui.win_x, ui.win_y),
        on_paths=ctl.paste_paths,
        on_window=_track,
        debug=debug,
    )


def _close_on_sigterm(win: Window) -> None:
    """Make SIGTERM (``terminux --stop``, ``kill``) close the window as its
    close button does, so the state is saved. The GUI loop holds the main
    thread, where Python signal handlers run, so they may never get to; the
    C-level handler still writes the signal number to the wakeup fd at once,
    and a thread waiting on it closes the window."""
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    signal.set_wakeup_fd(write_fd)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: None)

    def wait() -> None:
        while os.read(read_fd, 1)[0] != signal.SIGTERM:  # Ctrl-C writes too
            pass
        win.destroy()

    threading.Thread(target=wait, daemon=True, name="sigterm").start()


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
    # No close handler: the remote server keeps running, and there's no
    # local controller to flush.
    _open_window(
        remote_url,
        # No per-client persistence: every connection opens at the default size.
        geometry=(UiPrefs.win_w, UiPrefs.win_h, None, None),
        on_paths=lambda paths: _post_paste_paths(remote_url, paths),
        debug=debug,
    )


def _paste_from_python(webview_mod: _WebviewModuleLike) -> Callable[[], None]:
    """Edit → Paste on Windows: a menu click gives the webview no keystroke
    to paste from, and WebView2 refuses the page's clipboard API, so read
    the clipboard here and hand the text to the page."""

    def callback() -> None:
        win = webview_mod.active_window()
        if win is not None:
            text = json.dumps(clipboard.read_text())
            win.evaluate_js(f"window.terminux?.pasteText({text})")

    return callback


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

    def _on_window(
        action: Callable[[_WebviewWindowLike], object],
    ) -> Callable[[], None]:
        def callback() -> None:
            win = webview_mod.active_window()
            if win is not None:
                action(win)

        return callback

    def _cmd(command_id: str) -> Callable[[], None]:
        js = f"window.terminux?.invoke({json.dumps(command_id)})"
        return _on_window(lambda w: w.evaluate_js(js))

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
        MenuAction("Sort by Recent Activity", _cmd("workspace.sort.recent")),
        MenuAction("Sort by Time Spent", _cmd("workspace.sort.time-spent")),
    ])

    view_items: list[MenuEntry] = [
        MenuAction("Quick Switcher", _cmd("palette.quick")),
        MenuAction("Command Palette", _cmd("palette.command")),
        MenuSeparator(),
        MenuAction("Find…", _cmd("view.find")),
        MenuAction("Usage Stats", _cmd("view.stats")),
        MenuAction("Remote Connection URL", _cmd("view.connect-info")),
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
    ]
    if sys.platform == "darwin":
        # pywebview's own View menu, holding only this item, is turned off
        # in ``_open_window``: next to ours, it looked like ours with most
        # entries missing.
        view_items.extend([
            MenuSeparator(),
            MenuAction(
                "Toggle Full Screen", _on_window(lambda w: w.toggle_fullscreen())
            ),
        ])

    menus = [
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
        Menu("View", view_items),
        Menu("Workspace", workspace_items),
        Menu("Help", [MenuAction("Documentation", _url(DOCS_URL))]),
    ]
    # pywebview gives macOS windows a native Edit menu (Copy, Paste, Select
    # All); Windows and Linux windows get none, and no context menu either.
    if sys.platform != "darwin":
        edit_items = [
            MenuAction("Copy", _cmd("edit.copy")),
            MenuAction(
                "Paste",
                _paste_from_python(webview_mod)
                if sys.platform == "win32"
                else _cmd("edit.paste"),
            ),
            MenuSeparator(),
            MenuAction("Select All", _cmd("edit.select-all")),
        ]
        menus.insert(1, Menu("Edit", edit_items))
    return menus


if __name__ == "__main__":
    main()
