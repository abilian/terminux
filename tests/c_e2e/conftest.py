"""Live-server fixture for Playwright e2e (drives the URL, no pywebview)."""

from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING

import pytest
import uvicorn

from terminux.server.asgi import build_app
from terminux.server.auth import SESSION_TOKEN

if TYPE_CHECKING:
    from collections.abc import Iterator


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def app_url() -> Iterator[str]:
    """A fresh, isolated server per test (persist=False)."""
    port = _free_port()
    app = build_app(persist=False)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        ws="websockets-sansio",
    )
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/?t={SESSION_TOKEN}"
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
