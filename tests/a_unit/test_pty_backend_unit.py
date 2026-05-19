"""Deterministic unit tests for PTY backend helpers and branches.

These swap in a fake child process so terminate/exit_code/cwd branches are
exercised without depending on signals or the host OS.
"""

from __future__ import annotations

import signal
import subprocess

from terminux.core import pty_backend
from terminux.core.pty_backend import UnixPty, _darwin_cwd, _linux_cwd


class _FakeProc:
    def __init__(self, *, alive_seq=None, exitstatus=0, pid=4242) -> None:
        self._alive_seq = list(alive_seq or [False])
        self.exitstatus = exitstatus
        self.pid = pid
        self.fd = -1
        self.kills: list[int] = []
        self.wait_raises = False

    def isalive(self) -> bool:
        return self._alive_seq.pop(0) if self._alive_seq else False

    def kill(self, sig: int) -> None:
        self.kills.append(sig)

    def wait(self) -> None:
        if self.wait_raises:
            raise RuntimeError("boom")


def _unixpty(proc: _FakeProc) -> UnixPty:
    pty = UnixPty.__new__(UnixPty)
    pty._proc = proc  # type: ignore[attr-defined]
    return pty


def test_terminate_returns_when_already_dead() -> None:
    p = _FakeProc(alive_seq=[False])
    _unixpty(p).terminate()
    assert p.kills == []


def test_terminate_escalates_through_signals() -> None:
    # alive for the isalive() guard, then alive after HUP and TERM, dead after KILL
    p = _FakeProc(alive_seq=[True, True, True, False])
    _unixpty(p).terminate()
    assert p.kills == [signal.SIGHUP, signal.SIGTERM, signal.SIGKILL]


def test_terminate_stops_when_signal_oserrors() -> None:
    p = _FakeProc(alive_seq=[True, True])

    def boom(_sig: int) -> None:
        raise OSError

    p.kill = boom  # type: ignore[method-assign]
    _unixpty(p).terminate()  # OSError is swallowed, returns


def test_exit_code_none_while_alive() -> None:
    assert _unixpty(_FakeProc(alive_seq=[True])).exit_code() is None


def test_exit_code_value_and_wait_exception() -> None:
    assert _unixpty(_FakeProc(alive_seq=[False], exitstatus=7)).exit_code() == 7
    p = _FakeProc(alive_seq=[False])
    p.wait_raises = True
    assert _unixpty(p).exit_code() is None


def test_cwd_none_when_pid_missing() -> None:
    assert _unixpty(_FakeProc(pid=None)).cwd() is None


def test_linux_cwd_handles_missing_proc() -> None:
    assert _linux_cwd(2_147_483_000) is None


def test_darwin_cwd_no_lsof(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: None)
    assert _darwin_cwd(123) is None


def test_darwin_cwd_parses_lsof_output(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: "/usr/bin/lsof")

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(
            [], 0, stdout="p1\nfcwd\nn/var/tmp\n", stderr=""
        )

    monkeypatch.setattr(pty_backend.subprocess, "run", fake_run)
    assert _darwin_cwd(1) == "/var/tmp"


def test_darwin_cwd_no_match_and_error(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: "/usr/bin/lsof")
    monkeypatch.setattr(
        pty_backend.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 0, stdout="garbage\n", stderr=""
        ),
    )
    assert _darwin_cwd(1) is None

    def raises(*_a, **_k):
        raise OSError

    monkeypatch.setattr(pty_backend.subprocess, "run", raises)
    assert _darwin_cwd(1) is None


def test_cwd_dispatches_by_platform(monkeypatch) -> None:
    pty = _unixpty(_FakeProc(pid=99))
    monkeypatch.setattr(pty_backend.sys, "platform", "linux")
    monkeypatch.setattr(pty_backend, "_linux_cwd", lambda _pid: "/lx")
    assert pty.cwd() == "/lx"
    monkeypatch.setattr(pty_backend.sys, "platform", "darwin")
    monkeypatch.setattr(pty_backend, "_darwin_cwd", lambda _pid: "/mac")
    assert pty.cwd() == "/mac"
    monkeypatch.setattr(pty_backend.sys, "platform", "sunos")
    assert pty.cwd() is None


def test_unixpty_write_and_resize_swallow_oserror(monkeypatch) -> None:
    p = _FakeProc(alive_seq=[True])

    def bad_setwinsize(_r: int, _c: int) -> None:
        raise OSError

    p.setwinsize = bad_setwinsize  # type: ignore[attr-defined]
    pty = _unixpty(p)
    monkeypatch.setattr(
        pty_backend.os, "write", lambda *_a: (_ for _ in ()).throw(OSError)
    )
    pty.write(b"x")  # OSError suppressed
    pty.resize(80, 24)  # OSError suppressed


def test_spawn_pty_unix_smoke() -> None:
    from pathlib import Path

    pty = pty_backend.spawn_pty(["/bin/sh"], str(Path.cwd()), 80, 24)
    try:
        assert pty.is_alive() is True
        assert isinstance(pty.fd, int)
    finally:
        pty.terminate()
