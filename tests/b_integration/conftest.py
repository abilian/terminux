"""Shared live-server fixture for integration tests."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
import uvicorn

from terminux.server.asgi import AppController, build_app

if TYPE_CHECKING:
    from collections.abc import Iterator


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class LiveServer:
    url: str
    controller: AppController


@pytest.fixture
def server() -> Iterator[LiveServer]:
    port = free_port()
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
        yield LiveServer(f"http://127.0.0.1:{port}", app.state.controller)
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
