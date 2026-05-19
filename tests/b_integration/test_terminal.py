"""Integration tests for the PTY-backed Terminal and backend."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from terminux.core import pty_backend
from terminux.core.pty_backend import UnixPty, spawn_pty
from terminux.core.terminal import Terminal, TerminalRegistry


async def _drain(sub, needle: bytes, timeout: float = 6.0) -> bytes:
    async def go() -> bytes:
        buf = b""
        while True:
            _dropped, data, closed = await sub.drain()
            buf += data
            if needle in buf or closed:
                return buf

    return await asyncio.wait_for(go(), timeout)


def test_terminal_echo_and_backlog_replay() -> None:
    async def scenario() -> None:
        term = Terminal(["/bin/sh"], str(Path.cwd()), 80, 24)
        s1 = term.subscribe()
        term.write(b"echo hello_terminux\n")
        out = await _drain(s1, b"hello_terminux")
        assert b"hello_terminux" in out
        # A late subscriber gets the accumulated backlog replayed.
        s2 = term.subscribe()
        replay = await _drain(s2, b"hello_terminux", timeout=2)
        assert b"hello_terminux" in replay
        term.unsubscribe(s2)
        term.resize(120, 40)  # must not raise
        term.close()

    asyncio.run(scenario())


def test_terminal_exit_detection() -> None:
    async def scenario() -> int | None:
        codes: list[int | None] = []
        term = Terminal(["/bin/sh", "-c", "exit 7"], str(Path.cwd()), 80, 24)
        term.on_exit = codes.append
        deadline = time.time() + 6
        while not term.exited and time.time() < deadline:
            await asyncio.sleep(0.05)
        assert term.exited is True
        term.write(b"ignored\n")  # write after exit is a no-op
        term.resize(10, 10)
        # Subscribing after exit immediately drains as closed.
        sub = term.subscribe()
        _dropped, _data, closed = await asyncio.wait_for(sub.drain(), timeout=2)
        assert closed is True
        return codes[0] if codes else term.exit_code

    assert asyncio.run(scenario()) == 7


def test_terminal_registry() -> None:
    async def scenario() -> None:
        reg = TerminalRegistry()
        t = reg.create(["/bin/sh"], str(Path.cwd()), 80, 24)
        assert reg.get(t.id) is t
        reg.close(t.id)
        assert reg.get(t.id) is None
        reg.close("missing")  # no-op
        reg.create(["/bin/sh"], str(Path.cwd()), 80, 24)
        reg.close_all()

    asyncio.run(scenario())


def test_unixpty_cwd_reports_spawn_directory(tmp_path: Path) -> None:
    target = str(Path(tmp_path).resolve())
    pty = UnixPty(["/bin/sh"], target, 80, 24)
    try:
        deadline = time.time() + 6
        while time.time() < deadline and pty.cwd() != target:
            time.sleep(0.1)
        assert pty.cwd() == target
    finally:
        pty.terminate()


def test_unixpty_lifecycle_after_exit() -> None:
    pty = UnixPty(["/bin/sh", "-c", "exit 0"], str(Path.cwd()), 80, 24)
    deadline = time.time() + 6
    while time.time() < deadline and pty.is_alive():
        time.sleep(0.05)
    assert pty.is_alive() is False
    pty.terminate()  # already dead -> early return
    assert pty.exit_code() == 0


def test_spawn_pty_windows_not_implemented(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend.sys, "platform", "win32")
    with pytest.raises(NotImplementedError):
        spawn_pty(["x"], ".", 80, 24)
