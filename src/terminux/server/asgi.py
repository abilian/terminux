"""Starlette app composition root.

Builds the ASGI application by wiring together:

- ``AppController`` — domain state + live terminals (``./controller.py``)
- ``Api``           — HTTP/WebSocket route handlers (``./api.py``)
- ``SecurityHeadersMiddleware`` — CSP + hardening (``./middleware.py``)

``AppController`` and the activity constants are re-exported here so
existing callers (``from terminux.server.asgi import AppController``,
test code that reads ``asgi.UNSEEN_GRACE_SECONDS``) keep working.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from terminux.server.api import STATIC_DIR, Api
from terminux.server.controller import (
    ACTIVITY_IDLE_THRESHOLD,
    READY_TRANSITION_SECONDS,
    UNSEEN_GRACE_SECONDS,
    AppController,
)
from terminux.server.middleware import SecurityHeadersMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


__all__ = [
    "ACTIVITY_IDLE_THRESHOLD",
    "READY_TRANSITION_SECONDS",
    "UNSEEN_GRACE_SECONDS",
    "AppController",
    "build_app",
]


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
