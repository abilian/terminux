"""Shared pytest fixtures and configuration.

Test Pyramid Structure:
- tests/a_unit/        - Unit tests (fast, isolated, no I/O)
- tests/b_integration/ - Integration tests (component interactions, file I/O)
- tests/c_e2e/         - End-to-end tests (full app/CLI workflows)

Run specific test types:
    uv run pytest -m unit              # Run only unit tests
    uv run pytest -m integration       # Run only integration tests
    uv run pytest -m e2e               # Run only e2e tests
    uv run pytest tests/a_unit/        # Run by directory
"""

from __future__ import annotations

import shutil
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import uvicorn

from terminux.server.asgi import build_app

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from starlette.applications import Starlette

    from terminux.server.controller import AppController


def pytest_collection_modifyitems(config, items):
    """Automatically apply markers based on test directory."""
    for item in items:
        # Get the path relative to tests/
        test_path = Path(item.fspath)
        parts = test_path.parts

        # Apply markers based on directory
        if "a_unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "b_integration" in parts:
            item.add_marker(pytest.mark.integration)
        elif "c_e2e" in parts:
            item.add_marker(pytest.mark.e2e)


# -----------------------------------------------------------------------------
# Shared Fixtures
# -----------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"

# A profile-free PowerShell whose prompt reports the cwd (OSC 9;9): on
# Windows that's the only way terminux learns it (no /proc, no libproc).
_PS_PROMPT = 'function prompt { "$([char]27)]9;9;$($PWD.ProviderPath)$([char]7)PS> " }'


@dataclass(frozen=True)
class PortableShell:
    """A fast shell for tests (no user profile), with portable commands.

    ``/bin/sh`` on Unix; ``pwsh`` (or Windows PowerShell) on Windows.
    Type commands with ``\r`` (Enter), which both accept.
    """

    argv: list[str]

    @property
    def is_powershell(self) -> bool:
        return Path(self.argv[0]).stem.lower() in {"pwsh", "powershell"}

    def exit_argv(self, code: int) -> list[str]:
        """A shell that exits at once with ``code``."""
        if self.is_powershell:
            return [self.argv[0], "-NoLogo", "-NoProfile", "-Command", f"exit {code}"]
        return [self.argv[0], "-c", f"exit {code}"]

    def size_command(self, marker: str) -> str:
        """Prints ``<marker> <rows> <cols>`` as the shell sees its tty."""
        if self.is_powershell:
            size = "$Host.UI.RawUI.WindowSize"
            return f'Write-Host "{marker} $({size}.Height) $({size}.Width)"'
        return f"echo {marker} $(stty size)"

    @property
    def exit_command(self) -> str:
        return "exit"


def _test_shell() -> PortableShell:
    if not IS_WINDOWS:
        return PortableShell(["/bin/sh"])
    exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
    return PortableShell([
        exe,
        "-NoLogo",
        "-NoProfile",
        "-NoExit",
        "-Command",
        _PS_PROMPT,
    ])


@pytest.fixture(scope="session")
def test_shell() -> PortableShell:
    return _test_shell()


def wait_until(predicate: Callable[[], object], timeout: float = 6.0) -> bool:
    """Poll ``predicate`` until it's truthy or ``timeout`` elapses; returns
    its last truthiness so callers can ``assert wait_until(...)``."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


@dataclass
class LiveServer:
    url: str
    controller: AppController
    app: Starlette


@pytest.fixture
def server(monkeypatch, test_shell: PortableShell) -> Iterator[LiveServer]:
    """A fresh, isolated uvicorn server per test (persist=False).

    Its tabs run the profile-free test shell, not the user's ``$SHELL -l``
    (slow, and different on every machine). The socket is bound here and
    handed to uvicorn, so no other process can grab the port in between;
    a server that fails to start fails the test instead of hanging it."""
    monkeypatch.setattr(
        "terminux.server.controller.default_shell", lambda: test_shell.argv
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = build_app(persist=False)
    config = uvicorn.Config(app, log_level="error", ws="websockets-sansio")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    started = wait_until(lambda: srv.started or not thread.is_alive(), timeout=10)
    assert started and srv.started, "test server failed to start"
    try:
        yield LiveServer(f"http://127.0.0.1:{port}", app.state.controller, app)
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
        sock.close()
