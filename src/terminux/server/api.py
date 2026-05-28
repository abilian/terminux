"""HTTP and WebSocket route handlers.

A thin Starlette-shaped shell over ``AppController``. Every method
either deny-checks the session token, mutates state under
``ctl.lock``, and shapes the result into a JSON / plaintext response,
or — for the PTY data plane — pumps bytes between an xterm WebSocket
and the underlying ``Terminal`` subscriber.
"""

from __future__ import annotations

import asyncio
import json
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
from terminux.server.auth import SESSION_TOKEN, token_ok

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.websockets import WebSocket

    from terminux.core.terminal import Subscriber, Terminal
    from terminux.server.controller import AppController


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR / "static"  # Vite build output (see frontend/)


def _deny(request: Request) -> Response | None:
    if not token_ok(request.query_params.get("t")):
        return PlainTextResponse("forbidden", status_code=403)
    return None


class Api:
    """HTTP/WebSocket handlers bound to a single controller."""

    def __init__(self, ctl: AppController) -> None:
        self.ctl = ctl

    # ----- static -------------------------------------------------------

    @staticmethod
    def index(_request: Request) -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__TOKEN__", SESSION_TOKEN))

    # ----- control plane ------------------------------------------------

    def get_state(self, request: Request) -> Response:
        return _deny(request) or JSONResponse(self.ctl.state_view())

    def create_workspace(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        # Display name tracks the shell's cwd (see _workspace_label); the
        # numbered name is just the fallback before a shell/cwd is known.
        with self.ctl.lock:
            ws = self.ctl.state.add_workspace()
            self.ctl.state.add_tab(ws.id)
            self.ctl.state.set_active_workspace(ws.id)
            self.ctl.save()
        return JSONResponse({"id": ws.id})

    async def patch_workspace(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        body: dict[str, Any] = await request.json()
        with self.ctl.lock:
            ws = self.ctl.state.get_workspace(request.path_params["ws_id"])
            if ws is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            if "name" in body:
                ws.name = str(body["name"]).strip() or ws.name
                ws.user_set_name = True  # pin it; stop tracking cwd
            if body.get("active"):
                self.ctl.state.set_active_workspace(ws.id)
            if "active_tab_id" in body:
                ws.active_tab_id = body["active_tab_id"]
                if ws.active_tab_id is not None:
                    tab = self.ctl.state.tabs.get(ws.active_tab_id)
                    if tab is not None:
                        tab.has_unseen_output = False
            if "order" in body:
                order = [str(x) for x in body["order"]]
                self.ctl.state.workspaces.sort(
                    key=lambda w: order.index(w.id) if w.id in order else 1_000_000,
                )
            if "tab_order" in body:
                want = [str(x) for x in body["tab_order"]]
                # Keep only ids that belong to this workspace; append any the
                # client omitted so no tab is ever lost on a stale reorder.
                ordered = [t for t in want if t in ws.tab_ids]
                ws.tab_ids = ordered + [t for t in ws.tab_ids if t not in ordered]
            self.ctl.save()
        return JSONResponse({"ok": True})

    def delete_workspace(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        ws_id = request.path_params["ws_id"]
        with self.ctl.lock:
            # Collect terminal ids and tab ids BEFORE removal — remove_workspace
            # drops the tabs from state, so we need the references first (and a
            # deliberate close also drops the saved scrollback for each tab).
            ws = self.ctl.state.get_workspace(ws_id)
            tab_ids: list[str] = list(ws.tab_ids) if ws is not None else []
            term_ids = [
                tab.terminal_id
                for tid in tab_ids
                if (tab := self.ctl.state.tabs.get(tid)) is not None
                and tab.terminal_id is not None
            ]
            self.ctl.state.remove_workspace(ws_id)
            for term_id in term_ids:
                self.ctl.terminals.close(term_id)
            for tid in tab_ids:
                self.ctl.delete_scrollback(tid)
            if not self.ctl.state.workspaces:
                ws = self.ctl.state.add_workspace(name="workspace 1")
                self.ctl.state.add_tab(ws.id)
                self.ctl.state.set_active_workspace(ws.id)
            self.ctl.save()
        return JSONResponse({"ok": True})

    def create_tab(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        ws_id = request.path_params["ws_id"]
        with self.ctl.lock:
            spawn_cwd = self.ctl.inherit_cwd(ws_id)
            tab = self.ctl.state.add_tab(ws_id, spawn_cwd=spawn_cwd)
            if tab is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            self.ctl.save()
        return JSONResponse({"id": tab.id})

    async def patch_tab(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        body: dict[str, Any] = await request.json()
        with self.ctl.lock:
            tab = self.ctl.state.tabs.get(request.path_params["tab_id"])
            if tab is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            if "title" in body:
                # Explicit rename pins the title.
                tab.title = str(body["title"]).strip() or tab.title
                tab.user_set_title = True
            elif "osc_title" in body and not tab.user_set_title:
                # OSC 0/2 from the shell — tracks unless the user pinned a name.
                tab.title = str(body["osc_title"]).strip() or tab.title
            self.ctl.save()
        return JSONResponse({"ok": True})

    async def patch_ui(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        body: dict[str, Any] = await request.json()
        with self.ctl.lock:
            ui = self.ctl.state.ui
            if "sidebar_width" in body:
                ui.sidebar_width = max(120, min(600, int(body["sidebar_width"])))
            if "font_size" in body:
                ui.font_size = max(6, min(32, int(body["font_size"])))
            for k in (
                "sidebar_collapsed",
                "copy_on_select",
                "scrollback_persist",
                "win_maximized",
            ):
                if k in body:
                    setattr(ui, k, bool(body[k]))
            for k in ("win_w", "win_h"):
                if k in body:
                    setattr(ui, k, max(200, int(body[k])))
            for k in ("win_x", "win_y"):
                if k in body:
                    setattr(ui, k, None if body[k] is None else int(body[k]))
            self.ctl.save()
        return JSONResponse({"ok": True})

    def delete_tab(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        tab_id = request.path_params["tab_id"]
        with self.ctl.lock:
            tab = self.ctl.state.tabs.get(tab_id)
            if tab is not None and tab.terminal_id is not None:
                self.ctl.terminals.close(tab.terminal_id)
            self.ctl.state.remove_tab(tab_id)
            # Deliberate close drops the captured scrollback too; restart-in-place
            # uses the dedicated DELETE /scrollback endpoint.
            self.ctl.delete_scrollback(tab_id)
            self.ctl.save()
        return JSONResponse({"ok": True})

    async def get_scrollback(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        tab_id = request.path_params["tab_id"]
        with self.ctl.lock:
            if self.ctl.state.tabs.get(tab_id) is None:
                return PlainTextResponse("", status_code=404)
            content = self.ctl.load_scrollback(tab_id) or ""
        return PlainTextResponse(content)

    async def put_scrollback(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        tab_id = request.path_params["tab_id"]
        body = await request.body()
        if len(body) > SCROLLBACK_MAX_BYTES * 2:
            # Reject obviously-oversized payloads up front; the helper still
            # tail-trims to the on-disk cap.
            return JSONResponse({"error": "too large"}, status_code=413)
        with self.ctl.lock:
            if self.ctl.state.tabs.get(tab_id) is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            if not self.ctl.state.ui.scrollback_persist:
                # Pref disabled: accept silently so the client doesn't retry.
                return JSONResponse({"ok": True})
            self.ctl.save_scrollback(tab_id, body.decode("utf-8", errors="replace"))
        return JSONResponse({"ok": True})

    async def delete_scrollback(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        self.ctl.delete_scrollback(request.path_params["tab_id"])
        return JSONResponse({"ok": True})

    async def reset_activity(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        with self.ctl.lock:
            self.ctl.reset_activity()
        return JSONResponse({"ok": True})

    async def open_url(  # noqa: PLR6301 — uniform Route handler shape across Api
        self,
        request: Request,
    ) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        body: dict[str, Any] = await request.json()
        url = str(body.get("url", "")).strip()
        if not url:
            return JSONResponse({"error": "missing url"}, status_code=400)
        if not open_url_in_default_app(url):
            return JSONResponse({"error": "rejected"}, status_code=400)
        return JSONResponse({"ok": True})

    async def spawn(self, request: Request) -> Response:
        if (deny := _deny(request)) is not None:
            return deny
        body: dict[str, Any] = await request.json()
        # Serialize PTY creation: concurrent openpty+spawn can stall output
        # pipes under rapid tab creation (technical spec §8).
        async with self.ctl.spawn_lock:
            term = self.ctl.ensure_terminal(
                request.path_params["tab_id"],
                int(body.get("cols", 80)),
                int(body.get("rows", 24)),
            )
        if term is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"terminal_id": term.id})

    # ----- data plane ---------------------------------------------------

    async def pty_ws(self, ws: WebSocket) -> None:
        if not token_ok(ws.query_params.get("t")):
            await ws.close(code=4403)
            return
        term = self.ctl.terminals.get(ws.path_params["terminal_id"])
        if term is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        sub = term.subscribe()
        out_task = asyncio.create_task(_pump_out(ws, sub, term))
        try:
            await _pump_in(ws, term, self.ctl)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            out_task.cancel()
            term.unsubscribe(sub)


async def _pump_out(ws: WebSocket, sub: Subscriber, term: Terminal) -> None:
    while True:
        dropped, data, closed = await sub.drain()
        if dropped:
            await ws.send_json({"type": "dropped"})
        if data:
            await ws.send_bytes(data)
        if closed:
            await ws.send_json({"type": "exit", "code": term.exit_code})
            return


async def _pump_in(ws: WebSocket, term: Terminal, ctl: AppController) -> None:
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            return
        data = message.get("bytes")
        if data is not None:
            # Real keystrokes from the user — credit the active workspace
            # with active-session time until idle silences it.
            ctl.note_input()
            term.write(data)
            continue
        text = message.get("text")
        if text is not None:
            msg = json.loads(text)
            if msg.get("type") == "resize":
                term.resize(int(msg["cols"]), int(msg["rows"]))
