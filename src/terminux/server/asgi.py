"""Starlette app: control plane (HTTP/JSON) + data plane (WebSocket per PTY)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess  # noqa: S404 — argv form only, no shell, opener path resolved via shutil.which
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from terminux.core.model import AppState, Workspace
from terminux.core.persistence import (
    SCROLLBACK_MAX_BYTES,
    delete_scrollback,
    load_scrollback,
    load_state,
    save_scrollback,
    save_state,
)
from terminux.core.shellprobe import default_cwd, default_shell
from terminux.core.terminal import Subscriber, Terminal, TerminalRegistry
from terminux.server.auth import SESSION_TOKEN, token_ok

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from starlette.requests import Request
    from starlette.websockets import WebSocket

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR / "static"  # Vite build output (see frontend/)

# Restrictive CSP: only same-origin bundled assets and the same-origin
# WebSocket; block remote origins, framing, and navigation away.
# 'unsafe-eval' is required by the pywebview runtime (it drives the webview
# via evaluate_js / injected code); the real protection here — no remote
# origins, no framing — is unaffected on a loopback, token-guarded server.
_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)


# Active-time tracker config: a workspace accrues seconds only while the
# user has typed into one of its tabs within this window. Captures real
# focus, ignores "left for lunch" and long-running commands the user
# isn't watching.
ACTIVITY_IDLE_THRESHOLD = 30.0  # seconds since last keystroke

# Window during which PTY output is treated as visit-cleanup, not real
# news. The moment a workspace is deactivated, the TUI's redraw tail and
# xterm's own settling effects (cursor restore, mode restoration, etc.)
# emit a stream of bytes that would otherwise flag the workspace as
# ``has_unseen_output=True`` — leaving a misleading green "ready for
# attention" dot the moment the user looks away.
UNSEEN_GRACE_SECONDS = 5.0

# Minimum sustained busy time before a busy→idle transition counts as
# a "task finished" ready signal. Filters out cosmetic blips and very
# short commands; Claude Code returning to its prompt after a real
# thinking session, ``sleep 10`` finishing without shell integration,
# and ``make test`` ending all cross this comfortably.
READY_TRANSITION_SECONDS = 5.0


class AppController:
    """Owns AppState + live terminals. All access is on the server event loop."""

    def __init__(self, *, persist: bool = True) -> None:
        self._persist = persist
        self.state: AppState = load_state() if persist else AppState.default()
        self.terminals = TerminalRegistry()
        self.spawn_lock = asyncio.Lock()  # serialize PTY creation (§8)
        # Starlette runs sync route handlers in anyio's threadpool, so multiple
        # of them can mutate `state` (and its `tabs` dict) concurrently. This
        # reentrant lock serializes every state access; route handlers acquire
        # it around the synchronous mutation block (never across `await`).
        self.lock = threading.RLock()
        # Per-workspace cumulative active seconds for this terminus session.
        # Transient (in-memory only) — resets when the process exits or when
        # the user explicitly invokes "Reset session activity counters".
        self._active_seconds: dict[str, float] = {}
        self._last_input_at: float | None = None
        # Wall-clock time when the activity session started, used to drive
        # the "session started Xm ago" header in the stats overlay.
        self._session_started_at: float = time.time()
        # Per-terminal busy-transition tracker. Used by the 1 Hz ticker to
        # detect busy→idle transitions that lasted long enough to count
        # as a "task finished" signal (drives the green "ready" dot).
        self._was_busy: dict[str, bool] = {}
        self._busy_since: dict[str, float] = {}

    def save(self) -> None:
        if not self._persist:
            return
        with self.lock:
            self._snapshot_cwds()
            save_state(self.state)

    def save_scrollback(self, tab_id: str, content: str) -> None:
        if not self._persist or not self.state.ui.scrollback_persist:
            return
        save_scrollback(tab_id, content)

    def load_scrollback(self, tab_id: str) -> str | None:
        if not self._persist or not self.state.ui.scrollback_persist:
            return None
        return load_scrollback(tab_id)

    def delete_scrollback(self, tab_id: str) -> None:
        # Always best-effort delete (even with persist=False, in case the
        # pref was toggled mid-run and a stale file lingers).
        if self._persist:
            delete_scrollback(tab_id)

    def note_input(self) -> None:
        """Called when keystrokes arrive over a PTY WebSocket — the only
        signal we treat as "user is actually working here right now"."""
        self._last_input_at = time.monotonic()

    def tick(self, dt: float, *, now: float | None = None) -> None:
        """Credit the active workspace with ``dt`` seconds iff the user has
        typed something in the last ``ACTIVITY_IDLE_THRESHOLD`` seconds.

        Called by the 1 Hz background ticker; ``now`` is injectable for
        deterministic testing.
        """
        if self._last_input_at is None:
            return
        current = now if now is not None else time.monotonic()
        if current - self._last_input_at > ACTIVITY_IDLE_THRESHOLD:
            return
        with self.lock:
            ws_id = self.state.active_workspace_id
            if ws_id is None or self.state.get_workspace(ws_id) is None:
                return
            self._active_seconds[ws_id] = self._active_seconds.get(ws_id, 0.0) + dt

    def active_seconds(self, ws_id: str) -> int:
        return int(self._active_seconds.get(ws_id, 0.0))

    def reset_activity(self) -> None:
        """Clear all per-workspace counters and start a fresh session."""
        self._active_seconds.clear()
        self._last_input_at = None
        self._session_started_at = time.time()

    @property
    def session_started_at(self) -> float:
        """Epoch seconds when the current activity session started."""
        return self._session_started_at

    def _snapshot_cwds(self) -> None:
        """Capture each live shell's cwd so a restart can respawn there.

        Iterates a list snapshot — callers may already hold ``self.lock`` (so
        the dict can't change underfoot), but ``list()`` makes the intent
        local to this method and survives anyone calling it without the lock.
        """
        for tab in list(self.state.tabs.values()):
            if tab.terminal_id is None:
                continue
            term = self.terminals.get(tab.terminal_id)
            if term is not None:
                live = term.cwd()
                if live:
                    tab.last_cwd = live

    def ensure_terminal(self, tab_id: str, cols: int, rows: int) -> Terminal | None:
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return None
            if tab.terminal_id is not None:
                existing = self.terminals.get(tab.terminal_id)
                if existing is not None and not existing.exited:
                    return existing
            cwd = tab.spawn_cwd or default_cwd()
            if not Path(cwd).is_dir():  # e.g. a restored dir since deleted
                cwd = default_cwd()
            term = self.terminals.create(default_shell(), cwd, cols, rows)
            tab.terminal_id = term.id
            term.on_activity = lambda: self._mark_activity(tab_id)
            term.on_attention = lambda: self._mark_ready(tab_id)
            term.on_exit = lambda _code: setattr(tab, "terminal_id", None)
            return term

    def inherit_cwd(self, ws_id: str) -> str | None:
        """Working directory of a workspace's currently active live shell."""
        with self.lock:
            ws = self.state.get_workspace(ws_id)
            if ws is None or ws.active_tab_id is None:
                return None
            tab = self.state.tabs.get(ws.active_tab_id)
            if tab is None or tab.terminal_id is None:
                return None
            term = self.terminals.get(tab.terminal_id)
            return term.cwd() if term is not None else None

    def active_terminal(self) -> Terminal | None:
        with self.lock:
            ws_id = self.state.active_workspace_id
            ws = self.state.get_workspace(ws_id) if ws_id else None
            if ws is None or ws.active_tab_id is None:
                return None
            tab = self.state.tabs.get(ws.active_tab_id)
            if tab is None or tab.terminal_id is None:
                return None
            return self.terminals.get(tab.terminal_id)

    def _workspace_label(self, ws: Workspace) -> str:
        """Display name: a pinned rename, else the **first** tab's directory.

        Tracks ``ws.tab_ids[0]`` rather than the active tab so jumping
        between tabs within a workspace doesn't keep renaming it; the
        drag-reorderable tab list gives the user a direct way to
        promote a different tab into the naming slot.

        Resolves to a directory immediately (never the numbered name): a
        live shell's cwd, else the last-seen cwd, else where it will spawn,
        else the default cwd. lsof is only run for the active workspace (or
        once per tab) to keep the per-poll cost bounded.
        """
        if ws.user_set_name:
            return ws.name
        cwd: str | None = None
        if ws.tab_ids:
            first_tid = ws.tab_ids[0]
            tab = self.state.tabs.get(first_tid)
            if tab is not None:
                if tab.terminal_id is not None:
                    term = self.terminals.get(tab.terminal_id)
                    is_active = ws.id == self.state.active_workspace_id
                    if term is not None and (is_active or tab.last_cwd is None):
                        live = term.cwd()
                        if live:
                            tab.last_cwd = live
                cwd = tab.last_cwd or tab.spawn_cwd
        if cwd is None:
            cwd = default_cwd()
        path = Path(cwd)
        if path == Path.home():
            return "~"
        return path.name or ws.name

    def state_view(self) -> dict[str, Any]:
        """`AppState.view_json` with cwd-derived workspace display names and
        a ``"busy"`` status promotion when a workspace has a foreground task
        running and nothing more urgent to signal (priority: active > exited
        > busy > unseen > idle). Computed on demand at view time so we never
        pay the ``tcgetpgrp`` syscall outside the ~2 Hz frontend poll.

        ``busy`` beats ``unseen`` because a chatty long-running task (Claude
        Code's spinner, a build's progress lines, ``tail -f``) would
        otherwise keep flipping the workspace green while it's still
        working. "Output happened" is only a useful "go check this" signal
        once the task has finished; until then "still running" is the
        more accurate cue.
        """
        with self.lock:
            view = self.state.view_json()
            view["session_started_at"] = self.session_started_at
            now = time.monotonic()
            by_id = {w.id: w for w in self.state.workspaces}
            for wv in view["workspaces"]:
                ws = by_id.get(wv["id"])
                if ws is None:
                    continue
                wv["name"] = self._workspace_label(ws)
                wv["active_seconds"] = self.active_seconds(ws.id)
                # Active/exited carry more urgent meaning and stay untouched.
                # Idle and unseen are both demoted to busy when any tab has
                # a foreground task running — UNLESS the workspace was just
                # deactivated: the visit-redraw tail / xterm settling would
                # otherwise paint the dot orange for the few seconds after
                # the user looked away.
                in_grace = ws.last_active_at is not None and (
                    now - ws.last_active_at < UNSEEN_GRACE_SECONDS
                )
                if (
                    wv["status"] in {"idle", "unseen"}
                    and not in_grace
                    and any(
                        (tab := self.state.tabs.get(tid)) is not None
                        and tab.terminal_id is not None
                        and (term := self.terminals.get(tab.terminal_id))
                        is not None
                        and term.is_busy()
                        for tid in ws.tab_ids
                    )
                ):
                    wv["status"] = "busy"
            return view

    def paste_paths(self, paths: list[str]) -> None:
        """Insert dropped file paths (shell-quoted) into the active terminal.

        Called from the pywebview thread; ``Terminal.write`` is a plain
        ``os.write`` to the PTY master, which is safe across threads.
        """
        term = self.active_terminal()
        if term is None or not paths:
            return
        text = " ".join(_shell_quote(p) for p in paths) + " "
        term.write(text.encode())

    def _mark_activity(self, tab_id: str) -> None:
        """Per-tab "output happened in a non-viewed tab" — drives the
        small activity indicator in the tab bar. Workspace-level "ready"
        is a separate signal handled by ``_mark_ready`` / the busy→idle
        tracker — generic output no longer flips the workspace dot."""
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return
            now = time.monotonic()
            for ws in self.state.workspaces:
                if tab_id not in ws.tab_ids:
                    continue
                is_active = (
                    ws.id == self.state.active_workspace_id
                    and ws.active_tab_id == tab_id
                )
                if is_active:
                    continue
                # Grace period: output within UNSEEN_GRACE_SECONDS of the
                # workspace being deactivated is treated as visit-cleanup
                # (redraw tail, xterm settling) and does not flag unseen.
                if ws.last_active_at is not None and (
                    now - ws.last_active_at < UNSEEN_GRACE_SECONDS
                ):
                    continue
                tab.has_unseen_output = True

    def _mark_ready(self, tab_id: str) -> None:
        """Fire the workspace-level "ready for review" signal. Called
        when one of the strict task-finished sources triggers: raw
        ``BEL`` outside any OSC, ``OSC 9`` notification, ``OSC 133;D``
        (≥ 2 s), or the kernel-level busy→idle transition (≥ 5 s,
        driven by ``poll_busy_transitions``).

        Skipped while the workspace is currently active or sitting in
        the post-visit grace window."""
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return
            now = time.monotonic()
            for ws in self.state.workspaces:
                if tab_id not in ws.tab_ids:
                    continue
                if ws.id == self.state.active_workspace_id:
                    continue
                if ws.last_active_at is not None and (
                    now - ws.last_active_at < UNSEEN_GRACE_SECONDS
                ):
                    continue
                ws.has_unseen_output = True

    def poll_busy_transitions(self) -> None:
        """1 Hz heartbeat: detect kernel-level busy→idle transitions. A
        terminal that was sustained-busy for at least
        ``READY_TRANSITION_SECONDS`` then went quiet is treated as
        "task finished" and feeds the workspace's "ready" signal — the
        same end-state as ``OSC 133;D`` but for shells/apps that don't
        speak shell-integration (Claude Code returning to its prompt,
        ``sleep 10`` ending, ``make test`` finishing without OSC 133)."""
        with self.lock:
            now = time.monotonic()
            for ws in self.state.workspaces:
                for tid in ws.tab_ids:
                    tab = self.state.tabs.get(tid)
                    if tab is None or tab.terminal_id is None:
                        continue
                    term = self.terminals.get(tab.terminal_id)
                    if term is None:
                        continue
                    term_id = term.id
                    is_busy_now = term.is_busy()
                    was_busy = self._was_busy.get(term_id, False)
                    if is_busy_now and not was_busy:
                        self._busy_since[term_id] = now
                    elif was_busy and not is_busy_now:
                        since = self._busy_since.pop(term_id, None)
                        if (
                            since is not None
                            and (now - since) >= READY_TRANSITION_SECONDS
                        ):
                            self._mark_ready(tid)
                    self._was_busy[term_id] = is_busy_now


def _shell_quote(path: str) -> str:
    """POSIX single-quote escaping so paths with spaces/specials are safe."""
    return "'" + path.replace("'", "'\\''") + "'"


def _deny(request: Request) -> Response | None:
    if not token_ok(request.query_params.get("t")):
        return PlainTextResponse("forbidden", status_code=403)
    return None


# Only schemes safe to hand to the OS opener — `file://`, `javascript:`,
# `data:` and friends are deliberately omitted.
_OPENABLE_SCHEMES = frozenset({"http", "https", "mailto"})


def _open_url_in_default_app(url: str) -> bool:
    """Open ``url`` in the OS's default application, never via the shell.

    pywebview's WKWebView ignores JavaScript ``window.open()``, so the
    Cmd/Ctrl+click web-links handler routes the URL here. Returns True if
    a real opener was dispatched; False if the URL was rejected or no
    opener exists on the platform.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _OPENABLE_SCHEMES:
        return False

    if sys.platform == "darwin":
        opener = "open"
    elif sys.platform.startswith("linux"):
        opener = "xdg-open"
    else:
        return False  # Windows path is unreachable in v1 (no PTY support).

    if shutil.which(opener) is None:
        return False

    try:
        # No shell, no env munging — argv only, so the URL is opaque.
        subprocess.Popen(  # noqa: S603 — argv form, opener is a literal
            [opener, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        log.exception("failed to spawn %s for url", opener)
        return False
    return True


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
        if not _open_url_in_default_app(url):
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach CSP and hardening headers to every HTTP response (§6)."""

    async def dispatch(  # noqa: PLR6301 (BaseHTTPMiddleware override must be a method)
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def build_app(*, persist: bool = True) -> Starlette:
    ctl = AppController(persist=persist)
    api = Api(ctl)
    routes = [
        Route("/", api.index),
        Route("/api/state", api.get_state),
        Route("/api/workspaces", api.create_workspace, methods=["POST"]),
        Route("/api/workspaces/{ws_id}", api.patch_workspace, methods=["PATCH"]),
        Route("/api/workspaces/{ws_id}", api.delete_workspace, methods=["DELETE"]),
        Route("/api/workspaces/{ws_id}/tabs", api.create_tab, methods=["POST"]),
        Route("/api/tabs/{tab_id}", api.patch_tab, methods=["PATCH"]),
        Route("/api/tabs/{tab_id}", api.delete_tab, methods=["DELETE"]),
        Route("/api/tabs/{tab_id}/spawn", api.spawn, methods=["POST"]),
        Route(
            "/api/tabs/{tab_id}/scrollback",
            api.get_scrollback,
            methods=["GET"],
        ),
        Route(
            "/api/tabs/{tab_id}/scrollback",
            api.put_scrollback,
            methods=["PUT"],
        ),
        Route(
            "/api/tabs/{tab_id}/scrollback",
            api.delete_scrollback,
            methods=["DELETE"],
        ),
        Route("/api/ui", api.patch_ui, methods=["PATCH"]),
        Route("/api/open-url", api.open_url, methods=["POST"]),
        Route("/api/activity/reset", api.reset_activity, methods=["POST"]),
        WebSocketRoute("/pty/{terminal_id}", api.pty_ws),
    ]

    async def _activity_ticker() -> None:
        """1 Hz: credit the active workspace with a second of active time
        when the user has typed in the last ACTIVITY_IDLE_THRESHOLD secs,
        and detect kernel-level busy→idle transitions that feed the
        workspace's "ready" signal."""
        while True:
            await asyncio.sleep(1.0)
            ctl.tick(1.0)
            ctl.poll_busy_transitions()

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(_activity_ticker())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = Starlette(
        routes=routes,
        middleware=[Middleware(SecurityHeadersMiddleware)],
        lifespan=lifespan,
    )
    app.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIR / "assets"),
        name="assets",
    )
    app.state.controller = ctl
    return app
