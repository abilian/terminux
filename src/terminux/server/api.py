"""HTTP and WebSocket route handlers.

A thin Starlette-shaped shell over ``AppController``. Every method
mutates state under ``ctl.lock`` and shapes the result into a JSON /
plaintext response, or — for the PTY data plane — pumps bytes between
an xterm WebSocket and the underlying ``Terminal`` subscriber.

Auth: HTTP routes are token-gated centrally in
``SecurityHeadersMiddleware`` (fail-closed); only the WebSocket route
checks the token here, because ``BaseHTTPMiddleware`` never sees
WebSocket connections.

Locking: handlers hold ``ctl.lock`` only around in-memory mutation and
call ``ctl.save()`` *after* releasing it — ``save()`` snapshots under
its own brief lock and runs the disk write (fsync!) unlocked, so no
lock is ever held across disk I/O.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from starlette.websockets import WebSocketDisconnect

from terminux.core.persistence import SCROLLBACK_MAX_BYTES
from terminux.openurl import open_url_in_default_app
from terminux.server import auth
from terminux.server.auth import LOOPBACK_BINDS, check_auth, client_ip

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.websockets import WebSocket

    from terminux.core.terminal import Subscriber, Terminal
    from terminux.server.controller import AppController


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR / "static"  # Vite build output (see frontend/)

# Clamp bounds for client-supplied UI prefs.
SIDEBAR_WIDTH_MIN, SIDEBAR_WIDTH_MAX = 120, 600
FONT_SIZE_MIN, FONT_SIZE_MAX = 6, 32
WIN_DIM_MIN = 200  # px; smaller would make the window unrecoverable
WIN_COORD_LIMIT = 100_000  # px; generous for any multi-monitor layout
# A PTY's size goes into a ``struct winsize`` (unsigned shorts); past that
# the fork child dies before exec. No screen fits 1000 columns anyway.
PTY_DIM_MIN, PTY_DIM_MAX = 1, 1000

# Reject scrollback uploads well past the on-disk cap up front; anything
# under this still gets tail-trimmed to SCROLLBACK_MAX_BYTES by the
# persistence helper. The 2x headroom tolerates a client whose local
# buffer briefly overshoots the cap between captures.
SCROLLBACK_REJECT_BYTES = SCROLLBACK_MAX_BYTES * 2


log = logging.getLogger(__name__)


class BadRequestError(ValueError):
    """A malformed request body; ``asgi`` renders it as a JSON 400."""


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as exc:  # JSONDecodeError, UnicodeDecodeError
        msg = f"body is not valid JSON: {exc}"
        raise BadRequestError(msg) from exc
    if not isinstance(body, dict):
        msg = "body must be a JSON object"
        raise BadRequestError(msg)
    return body


def _not_found(kind: str, ident: str) -> JSONResponse:
    return JSONResponse({"error": f"no {kind} {ident!r}"}, status_code=404)


def _check_types(body: dict[str, Any], **kinds: type) -> None:
    """400 before any state is touched, so nothing is half-applied."""
    for key, kind in kinds.items():
        if key in body and not isinstance(body[key], kind):
            msg = f"{key} must be a {kind.__name__}"
            raise BadRequestError(msg)


def _clamped_int(value: object, lo: int, hi: int, field: str) -> int:
    msg = f"{field} must be a number"
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BadRequestError(msg)
    try:
        n = round(value)
    except (ValueError, OverflowError) as exc:  # NaN, Infinity
        raise BadRequestError(msg) from exc
    return max(lo, min(hi, n))


class Api:
    """HTTP/WebSocket handlers bound to a single controller."""

    def __init__(self, ctl: AppController) -> None:
        self.ctl = ctl

    # ----- static -------------------------------------------------------

    @staticmethod
    def index(_request: Request) -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        # Looked up per request: ``--server`` swaps in the persistent token
        # after this module is imported.
        return HTMLResponse(html.replace("__TOKEN__", auth.SESSION_TOKEN))

    # ----- control plane ------------------------------------------------

    def get_state(self, _request: Request) -> Response:
        return JSONResponse(self.ctl.state_view())

    @staticmethod
    async def connect_info(request: Request) -> Response:
        """What another machine needs to reach this server.

        The frontend knows its own port and token, but not how this
        process was bound nor what this machine is called — both decide
        whether a remote client needs an SSH tunnel and what to put in
        it.
        """
        state = request.app.state
        # gethostname can consult the resolver, so keep it off the loop.
        hostname, lan_ip = await asyncio.to_thread(_network_identity)
        return JSONResponse({
            "hostname": hostname,
            "lan_ip": lan_ip,
            # --public-host, when given: the name the user says other
            # machines reach this one by, ahead of any guess.
            "public_host": state.public_host,
            "bind_host": state.bind_host,
            # The port the server itself listens on. In --connect mode
            # the client's own location says the tunnel's local port,
            # which is the wrong end to put in an ssh -L recipe.
            "port": state.bind_port,
            "loopback_only": state.bind_host in LOOPBACK_BINDS,
            # False in desktop mode: the port is ephemeral and the code
            # is regenerated per run, so the URL dies with the process.
            "stable_url": state.token_persistent,
        })

    def create_workspace(self, _request: Request) -> Response:
        # Display name tracks the shell's cwd (see _workspace_label); the
        # numbered name is just the fallback before a shell/cwd is known.
        with self.ctl.lock:
            ws = self.ctl.state.add_workspace()
            self.ctl.state.add_tab(ws.id)
            self.ctl.state.set_active_workspace(ws.id)
        self.ctl.save()
        return JSONResponse({"id": ws.id}, status_code=201)

    async def patch_workspace(self, request: Request) -> Response:
        body = await _json_object(request)
        _check_types(body, name=str, order=list, tab_order=list)
        ws_id = request.path_params["ws_id"]

        # All state access + the disk-touching ``save()`` runs in a worker
        # thread so a slow fsync (or anyone holding ``ctl.lock``) can't
        # freeze the asyncio loop — see ``notes/05-lessons-learned.md``.
        def _apply() -> bool:
            with self.ctl.lock:
                ws = self.ctl.state.get_workspace(ws_id)
                if ws is None:
                    return False
                if "name" in body:
                    ws.rename(body["name"])
                if body.get("active"):
                    self.ctl.state.set_active_workspace(ws.id)
                if "active_tab_id" in body:
                    self.ctl.state.set_active_tab(ws, body["active_tab_id"])
                if "order" in body:
                    self.ctl.state.reorder_workspaces(body["order"])
                if "tab_order" in body:
                    ws.reorder_tabs(body["tab_order"])
            self.ctl.save()
            return True

        if not await asyncio.to_thread(_apply):
            return _not_found("workspace", ws_id)
        return JSONResponse({"ok": True})

    def delete_workspace(self, request: Request) -> Response:
        self.ctl.close_workspace(request.path_params["ws_id"])
        return JSONResponse({"ok": True})

    def create_tab(self, request: Request) -> Response:
        ws_id = request.path_params["ws_id"]
        with self.ctl.lock:
            spawn_cwd = self.ctl.inherit_cwd(ws_id)
            tab = self.ctl.state.add_tab(ws_id, spawn_cwd=spawn_cwd)
        if tab is None:
            return _not_found("workspace", ws_id)
        self.ctl.save()
        return JSONResponse({"id": tab.id}, status_code=201)

    async def patch_tab(self, request: Request) -> Response:
        body = await _json_object(request)
        _check_types(body, title=str, osc_title=str)
        tab_id = request.path_params["tab_id"]

        def _apply() -> bool:
            with self.ctl.lock:
                tab = self.ctl.state.tabs.get(tab_id)
                if tab is None:
                    return False
                if "title" in body:
                    tab.rename(body["title"])
                elif "osc_title" in body and not tab.user_set_title:
                    # OSC 0/2 from the shell — tracks unless the user pinned a name.
                    tab.title = body["osc_title"].strip() or tab.title
            self.ctl.save()
            return True

        if not await asyncio.to_thread(_apply):
            return _not_found("tab", tab_id)
        return JSONResponse({"ok": True})

    async def patch_ui(self, request: Request) -> Response:
        # Validate/clamp up front (pure, outside the lock): a malformed field
        # is a 400 with nothing half-applied, not a 500 mid-mutation.
        updates = ui_updates(await _json_object(request))

        def _apply() -> None:
            with self.ctl.lock:
                for k, v in updates.items():
                    setattr(self.ctl.state.ui, k, v)
            self.ctl.save()

        await asyncio.to_thread(_apply)
        return JSONResponse({"ok": True})

    def delete_tab(self, request: Request) -> Response:
        tab_id = request.path_params["tab_id"]
        with self.ctl.lock:
            tab = self.ctl.state.tabs.get(tab_id)
            if tab is None:
                return _not_found("tab", tab_id)
            if not self.ctl.state.remove_tab(tab_id):
                msg = "a workspace keeps at least one tab; close the workspace"
                return JSONResponse({"error": msg}, status_code=409)
            if tab.terminal_id is not None:
                self.ctl.terminals.close(tab.terminal_id)
        # Deliberate close drops the captured scrollback too (restart-in-place
        # uses the dedicated DELETE /scrollback endpoint); the unlink runs
        # outside the lock (disk is never touched under it).
        self.ctl.delete_scrollback(tab_id)
        self.ctl.save()
        return JSONResponse({"ok": True})

    async def get_scrollback(self, request: Request) -> Response:
        tab_id = request.path_params["tab_id"]

        def _load() -> str | None:  # None signals "tab not found"
            with self.ctl.lock:
                if self.ctl.state.tabs.get(tab_id) is None:
                    return None
            # Disk read outside the lock — a slow or wedged volume must not
            # stall anyone queued on it (including the event loop via
            # ensure_terminal). A tab deleted between the check and the read
            # simply loads as absent.
            return self.ctl.load_scrollback(tab_id) or ""

        content = await asyncio.to_thread(_load)
        if content is None:
            return _not_found("tab", tab_id)
        return PlainTextResponse(content)

    async def put_scrollback(self, request: Request) -> Response:
        tab_id = request.path_params["tab_id"]
        body = await request.body()
        if len(body) > SCROLLBACK_REJECT_BYTES:
            return JSONResponse({"error": "too large"}, status_code=413)
        decoded = body.decode("utf-8", errors="replace")

        def _save() -> bool:  # False = tab not found
            with self.ctl.lock:
                if self.ctl.state.tabs.get(tab_id) is None:
                    return False
                if not self.ctl.state.ui.scrollback_persist:
                    # Pref disabled: accept silently so the client doesn't retry.
                    return True
            # Disk write (fsync!) outside the lock — the event loop queues on
            # this lock via ensure_terminal, so holding it here would stall
            # spawns (and the loop) for the fsync duration.
            self.ctl.save_scrollback(tab_id, decoded)
            with self.ctl.lock:
                gone = self.ctl.state.tabs.get(tab_id) is None
            if gone:  # tab deleted mid-write — don't resurrect its file
                self.ctl.delete_scrollback(tab_id)
            return True

        if not await asyncio.to_thread(_save):
            return _not_found("tab", tab_id)
        return JSONResponse({"ok": True})

    async def delete_scrollback(self, request: Request) -> Response:
        tab_id = request.path_params["tab_id"]
        await asyncio.to_thread(self.ctl.delete_scrollback, tab_id)
        return JSONResponse({"ok": True})

    async def reset_activity(self, _request: Request) -> Response:
        # In-memory only, but it competes for ``ctl.lock`` — run it in a
        # worker thread so the asyncio loop stays free if the lock is held.
        await asyncio.to_thread(self.ctl.reset_activity)
        return JSONResponse({"ok": True})

    async def open_url(  # noqa: PLR6301 — uniform Route handler shape across Api
        self,
        request: Request,
    ) -> Response:
        body = await _json_object(request)
        _check_types(body, url=str)
        url = body.get("url", "").strip()
        if not url:
            msg = "missing url"
            raise BadRequestError(msg)
        # open_url_in_default_app does ``shutil.which`` + Popen — both
        # potentially slow under load, so keep them off the event loop.
        if not await asyncio.to_thread(open_url_in_default_app, url):
            msg = "rejected: not an http, https or mailto URL, or no opener here"
            raise BadRequestError(msg)
        return JSONResponse({"ok": True})

    async def paste_paths(self, request: Request) -> Response:
        """Paste shell-quoted paths into the currently active terminal.

        Used by the file-drop handler. In desktop mode the local pywebview
        bridge calls ``ctl.paste_paths`` directly; in ``--connect`` mode
        the client POSTs here so the same affordance works against a
        remote backend.
        """
        body = await _json_object(request)
        _check_types(body, paths=list)
        paths = [str(p) for p in body.get("paths", [])]
        # ``paste_paths`` writes via ``os.write`` to a PTY master, which
        # can block briefly under input-buffer backpressure — offload it.
        await asyncio.to_thread(self.ctl.paste_paths, paths)
        return JSONResponse({"ok": True})

    async def spawn(self, request: Request) -> Response:
        body = await _json_object(request)
        cols = _clamped_int(body.get("cols", 80), PTY_DIM_MIN, PTY_DIM_MAX, "cols")
        rows = _clamped_int(body.get("rows", 24), PTY_DIM_MIN, PTY_DIM_MAX, "rows")
        # Serialize PTY creation: concurrent openpty+spawn can stall output
        # pipes under rapid tab creation (technical spec §8). The fork/exec
        # itself runs in a worker thread inside ensure_terminal; only
        # attaching the reader to the loop happens here.
        async with self.ctl.spawn_lock:
            term = await self.ctl.ensure_terminal(
                request.path_params["tab_id"], cols, rows
            )
        if term is None:
            return _not_found("tab", request.path_params["tab_id"])
        return JSONResponse({"terminal_id": term.id})

    # ----- data plane ---------------------------------------------------

    async def pty_ws(self, ws: WebSocket) -> None:
        # Closing before ``accept`` refuses the handshake: the client sees
        # an HTTP 403 either way (a close code would never reach it).
        if not check_auth(ws.query_params.get("t"), client_ip(ws)):
            await ws.close()
            return
        term = self.ctl.terminals.get(ws.path_params["terminal_id"])
        if term is None:
            await ws.close()
            return
        await ws.accept()
        sub = term.subscribe()
        out_task = asyncio.create_task(_pump_out(ws, sub, term))
        try:
            await _pump_in(ws, term, sub, self.ctl)
        except WebSocketDisconnect:
            pass
        finally:
            out_task.cancel()
            # Collect the pump's outcome; a send on a socket that just
            # closed is expected, anything else surfaces.
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await out_task
            term.unsubscribe(sub)


def _network_identity() -> tuple[str, str | None]:
    """This machine's hostname and best-effort LAN address.

    The address is found by pointing a UDP socket at an unroutable
    documentation address (RFC 5737): that makes the kernel pick the
    interface it would route through and assign a source address, with
    no packet sent and nothing to be reachable. ``None`` when the host
    has no route out (offline, or loopback only).
    """
    hostname = socket.gethostname()
    with (
        contextlib.suppress(OSError),
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
    ):
        sock.connect(("192.0.2.1", 53))
        return hostname, str(sock.getsockname()[0])
    return hostname, None


def ui_updates(body: dict[str, Any]) -> dict[str, Any]:
    """Clamp a ``PATCH /api/ui`` body into UiPrefs attribute assignments.

    Pure: raises ``BadRequestError`` on a malformed field without touching any
    state, so nothing is half-applied.
    """
    updates: dict[str, Any] = {}
    if "sidebar_width" in body:
        updates["sidebar_width"] = _clamped_int(
            body["sidebar_width"], SIDEBAR_WIDTH_MIN, SIDEBAR_WIDTH_MAX, "sidebar_width"
        )
    if "font_size" in body:
        updates["font_size"] = _clamped_int(
            body["font_size"], FONT_SIZE_MIN, FONT_SIZE_MAX, "font_size"
        )
    flags = ("sidebar_collapsed", "copy_on_select", "scrollback_persist")
    _check_types(body, **dict.fromkeys(flags, bool))
    updates.update({k: body[k] for k in flags if k in body})
    for k in ("win_w", "win_h"):
        if k in body:
            updates[k] = _clamped_int(body[k], WIN_DIM_MIN, WIN_COORD_LIMIT, k)
    for k in ("win_x", "win_y"):
        if k in body:
            updates[k] = (
                None
                if body[k] is None
                else _clamped_int(body[k], -WIN_COORD_LIMIT, WIN_COORD_LIMIT, k)
            )
    return updates


async def _pump_out(ws: WebSocket, sub: Subscriber, term: Terminal) -> None:
    while True:
        dropped, data, closed = await sub.drain()
        owner = sub.take_owner_news()
        if owner is not None:
            await ws.send_json({"type": "owner", "owner": owner})
        if dropped:
            await ws.send_json({"type": "dropped"})
        if data:
            await ws.send_bytes(data)
        if closed:
            await ws.send_json({"type": "exit", "code": term.exit_code})
            return


async def _pump_in(
    ws: WebSocket, term: Terminal, sub: Subscriber, ctl: AppController
) -> None:
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            if not term.is_owner(sub):
                # A watching client's bytes are its emulator's automatic
                # answers to the program's queries (cursor position, device
                # attributes) describing the wrong screen. Its user's real
                # input always follows a "claim" that makes it the owner.
                continue
            # Real keystrokes from the user — credit the active workspace
            # with active-session time until idle silences it.
            ctl.note_input(term.id)
            # ``term.write`` may wait for PTY input-queue space (the fd is
            # non-blocking, but a paste large enough to fill the kernel's
            # input buffer — ~4 KB on macOS — makes it select() until the
            # shell drains). Offloading to a worker thread limits the blast
            # radius of a stuck shell to that one terminal; the loop stays
            # free.
            await asyncio.to_thread(term.write, data)
            continue
        text = message.get("text")
        if text is not None:
            try:
                _apply_control(text, term, sub)
            except ValueError as exc:  # one bad frame must not drop the terminal
                log.warning("ignored malformed control frame: %s", exc)


def _apply_control(text: str, term: Terminal, sub: Subscriber) -> None:
    """Apply one JSON control frame from the client (resize or claim)."""
    msg = json.loads(text)
    if not isinstance(msg, dict):
        err = "control frame must be a JSON object"
        raise BadRequestError(err)
    # Both may resize the PTY — a ``TIOCSWINSZ`` ioctl, non-blocking, no
    # offload needed.
    kind = msg.get("type")
    if kind == "resize":
        cols = _clamped_int(msg.get("cols"), PTY_DIM_MIN, PTY_DIM_MAX, "cols")
        rows = _clamped_int(msg.get("rows"), PTY_DIM_MIN, PTY_DIM_MAX, "rows")
        term.report_size(sub, cols, rows)
    elif kind == "claim":
        term.claim(sub)
