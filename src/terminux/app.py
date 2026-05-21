"""Entrypoint: run the loopback server, then host it in a pywebview window.

``--no-window`` runs the server headless (browse to the printed URL) — used
for development and e2e tests, and a preview of the future "web mode".
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import socket
import sys
import threading
import time
from typing import cast

import uvicorn

from terminux.server.asgi import AppController, build_app
from terminux.server.auth import SESSION_TOKEN

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
    webview.start()


if __name__ == "__main__":
    main()
