"""Entrypoint: run the loopback server, then host it in a pywebview window.

``--no-window`` runs the server headless (browse to the printed URL) — used
for development and e2e tests, and a preview of the future "web mode".
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import socket
import sys
import threading
import time
from typing import TYPE_CHECKING, Protocol, cast

import uvicorn

from terminux.constants import DOCS_URL
from terminux.openurl import open_url_in_default_app
from terminux.server.asgi import AppController, build_app
from terminux.server.auth import SESSION_TOKEN

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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="terminux")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="run the server only (no desktop window)",
    )
    parser.add_argument("--port", type=int, default=0, help="bind port (0 = ephemeral)")
    parser.add_argument(
        "--host",
        default=HOST,
        help="bind address (default 127.0.0.1; use 0.0.0.0 for container/web mode)",
    )
    args = parser.parse_args()

    port = args.port or _free_port()
    app = build_app(persist=True)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=port,
        log_level="warning",
        ws="websockets-sansio",  # avoid the deprecated legacy websockets impl
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=_serve, args=(server,), daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)

    shown_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host  # noqa: S104
    url = f"http://{shown_host}:{port}/?t={SESSION_TOKEN}"
    log.info("terminux server ready at %s", url)

    if args.no_window:
        with contextlib.suppress(KeyboardInterrupt):
            thread.join()
        return

    _run_windowed(url, app.state.controller, server)


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


def _run_windowed(url: str, ctl: AppController, server: uvicorn.Server) -> None:
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
    # ``webview`` is a real module; the cast is purely to tell the static
    # checker that we'll only touch ``.active_window`` on it (which it
    # does have, but the module stubs don't declare).
    webview.start(menu=_build_menu(cast("_WebviewModuleLike", webview)))


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
        MenuAction("Reorder by Activity", _cmd("workspace.reorder-by-activity")),
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
