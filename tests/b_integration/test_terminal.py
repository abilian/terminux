"""Integration tests for the PTY-backed Terminal and backend."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from terminux.core import pty_backend
from terminux.core.pty_backend import spawn_pty
from terminux.core.terminal import Terminal, TerminalRegistry

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY")
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="ConPTY")


async def _drain(sub, needle: bytes, timeout: float = 6.0) -> bytes:
    async def go() -> bytes:
        buf = b""
        while True:
            _dropped, data, closed = await sub.drain()
            buf += data
            if needle in buf or closed:
                return buf

    return await asyncio.wait_for(go(), timeout)


def test_terminal_echo_and_backlog_replay(test_shell) -> None:
    async def scenario() -> None:
        term = Terminal(spawn_pty(test_shell.argv, str(Path.cwd()), 80, 24))
        s1 = term.subscribe()
        term.write(b"echo hello_terminux\r")
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


def test_terminal_exit_detection(test_shell) -> None:
    async def scenario() -> int | None:
        codes: list[int | None] = []
        term = Terminal(spawn_pty(test_shell.exit_argv(7), str(Path.cwd()), 80, 24))
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


def test_terminal_registry(test_shell) -> None:
    async def scenario() -> None:
        reg = TerminalRegistry()
        t = reg.adopt(spawn_pty(test_shell.argv, str(Path.cwd()), 80, 24))
        assert reg.get(t.id) is t
        reg.close(t.id)
        assert reg.get(t.id) is None
        reg.close("missing")  # no-op
        reg.adopt(spawn_pty(test_shell.argv, str(Path.cwd()), 80, 24))
        reg.close_all()

    asyncio.run(scenario())


def test_spawn_failure_is_an_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):  # noqa: PT011
        spawn_pty([str(tmp_path / "no-such-shell")], str(tmp_path), 80, 24)


def _resolved(path: str | None) -> str | None:
    return str(Path(path).resolve()) if path else None


@unix_only
def test_unixpty_cwd_reports_spawn_directory(tmp_path: Path) -> None:
    # libproc reports the *as-recorded* cwd (e.g. ``/tmp/...``) while the
    # tmp_path fixture canonicalises through symlinks to ``/private/tmp/...``
    # on macOS. Compare resolved forms so we're checking "same directory",
    # not "same string".
    target = str(Path(tmp_path).resolve())
    pty = pty_backend.UnixPty(["/bin/sh"], target, 80, 24)
    try:
        deadline = time.time() + 6
        while time.time() < deadline and _resolved(pty.cwd()) != target:
            time.sleep(0.1)
        assert _resolved(pty.cwd()) == target
    finally:
        pty.terminate()


@unix_only
def test_unixpty_lifecycle_after_exit() -> None:
    pty = pty_backend.UnixPty(["/bin/sh", "-c", "exit 0"], str(Path.cwd()), 80, 24)
    deadline = time.time() + 6
    while time.time() < deadline and pty.is_alive():
        time.sleep(0.05)
    assert pty.is_alive() is False
    pty.terminate()  # already dead -> early return
    assert pty.exit_code() == 0


def test_spawn_pty_dispatches_on_platform(monkeypatch) -> None:
    made: list[str] = []
    monkeypatch.setattr(pty_backend, "WindowsPty", lambda *_a: made.append("win"))
    monkeypatch.setattr(pty_backend, "UnixPty", lambda *_a: made.append("unix"))
    for platform in ("win32", "linux", "darwin"):
        monkeypatch.setattr(pty_backend.sys, "platform", platform)
        spawn_pty(["x"], ".", 80, 24)
    assert made == ["win", "unix", "unix"]


# ----- Windows (ConPTY) -------------------------------------------------


@windows_only
def test_windows_terminal_learns_cwd_from_osc_9_9(test_shell, tmp_path: Path) -> None:
    """No API reads another process's cwd on Windows: the test shell's
    prompt reports it, and that's what ``Terminal.cwd`` returns."""

    async def scenario() -> None:
        term = Terminal(spawn_pty(test_shell.argv, str(tmp_path), 80, 24))
        try:
            assert term._pty.cwd() is None
            sub = term.subscribe()
            await _drain(sub, b"PS> ")
            assert term.cwd() == str(tmp_path)
            (tmp_path / "sub dir").mkdir()
            term.write(b"cd 'sub dir'\r")
            deadline = time.time() + 6
            while time.time() < deadline and term.cwd() != str(tmp_path / "sub dir"):
                await asyncio.sleep(0.1)
            assert term.cwd() == str(tmp_path / "sub dir")
        finally:
            term.close()

    asyncio.run(scenario())


@windows_only
def test_windows_terminal_multibyte_output_and_busy(test_shell) -> None:
    async def scenario() -> None:
        term = Terminal(spawn_pty(test_shell.argv, str(Path.cwd()), 80, 24))
        try:
            sub = term.subscribe()
            await _drain(sub, b"PS> ")
            assert term._pty.foreground_busy() is False  # idle at the prompt
            # Built from code points, so the echoed command line can't match.
            expected = "é€".encode() * 300
            term.write(b"Write-Host ([string]::new([char[]](0xe9, 0x20ac)) * 300)\r")
            out = await _drain(sub, expected)
            assert expected in out
            assert "�".encode() not in out  # no character split in two
            term.write(b"ping -n 4 127.0.0.1\r")
            await _drain(sub, b"127.0.0.1:")
            assert term._pty.foreground_busy() is True  # a child is running
        finally:
            term.close()

    asyncio.run(scenario())


@windows_only
def test_windows_close_ends_the_shell_without_blocking(test_shell) -> None:
    async def scenario() -> None:
        pty = spawn_pty(test_shell.argv, str(Path.cwd()), 80, 24)
        term = Terminal(pty)
        await _drain(term.subscribe(), b"PS> ")
        start = time.perf_counter()
        term.close()
        assert time.perf_counter() - start < 0.5  # never blocks the loop
        deadline = time.time() + 6
        while time.time() < deadline and pty.is_alive():
            await asyncio.sleep(0.05)
        assert pty.is_alive() is False

    asyncio.run(scenario())


@windows_only
def test_windows_terminate_before_attach_ends_the_shell(test_shell) -> None:
    """The tab closed while its shell was spawning: never attached."""
    pty = spawn_pty(test_shell.argv, str(Path.cwd()), 80, 24)
    pty.terminate()
    deadline = time.time() + 6
    while time.time() < deadline and pty.is_alive():
        time.sleep(0.05)
    assert pty.is_alive() is False
