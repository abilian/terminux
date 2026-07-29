"""Deterministic unit tests for PTY backend helpers and branches.

These swap in a fake child process so terminate/exit_code/cwd branches are
exercised without depending on signals or the host OS.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from terminux.core import pty_backend
from terminux.core.pty_backend import (
    UnixPty,
    _darwin_cwd,
    _libproc_cwd,
    _linux_cwd,
)


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
    monkeypatch.setattr(pty_backend, "_libproc_cwd", lambda _pid: None)
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: None)
    assert _darwin_cwd(123) is None


def test_darwin_cwd_parses_lsof_output(monkeypatch) -> None:
    # libproc is tried first; force the fallback to exercise the lsof parser.
    monkeypatch.setattr(pty_backend, "_libproc_cwd", lambda _pid: None)
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: "/usr/bin/lsof")

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(
            [], 0, stdout="p1\nfcwd\nn/var/tmp\n", stderr=""
        )

    monkeypatch.setattr(pty_backend.subprocess, "run", fake_run)
    assert _darwin_cwd(1) == "/var/tmp"


def test_darwin_cwd_no_match_and_error(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend, "_libproc_cwd", lambda _pid: None)
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


def test_darwin_cwd_prefers_libproc(monkeypatch) -> None:
    """If libproc returns a value, lsof is never consulted."""
    monkeypatch.setattr(pty_backend, "_libproc_cwd", lambda _pid: "/from/libproc")

    def boom(*_a, **_k):
        raise AssertionError("lsof fallback should not run")

    monkeypatch.setattr(pty_backend.shutil, "which", boom)
    assert _darwin_cwd(1) == "/from/libproc"


@pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS-only")
def test_libproc_cwd_resolves_current_process() -> None:
    """End-to-end: real kernel call returns this process's actual cwd."""
    expected = str(Path.cwd().resolve())
    got = _libproc_cwd(os.getpid())
    assert got is not None
    assert str(Path(got).resolve()) == expected


@pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS-only")
def test_libproc_cwd_returns_none_for_invalid_pid() -> None:
    # A PID well beyond typical kernel pid_max — proc_pidinfo returns 0.
    assert _libproc_cwd(2_147_483_000) is None


def test_libproc_cwd_returns_none_when_symbol_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend, "_proc_pidinfo", None)
    assert _libproc_cwd(1) is None


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


def test_unixpty_write_retries_on_eagain_and_partial(monkeypatch) -> None:
    p = _FakeProc()
    p.fd = 9
    attempts: list[bytes] = []
    waited: list[list[int]] = []

    def fake_write(_fd: int, view) -> int:
        attempts.append(bytes(view))
        if len(attempts) == 1:
            raise BlockingIOError
        return 2  # partial write: two bytes per call

    monkeypatch.setattr(pty_backend.os, "write", fake_write)
    monkeypatch.setattr(
        pty_backend.select, "select", lambda _r, w, _x: waited.append(w) or ([], w, [])
    )
    _unixpty(p).write(b"abcd")
    # EAGAIN → wait for writability once, then drain in partial chunks.
    assert waited == [[9]]
    assert attempts == [b"abcd", b"abcd", b"cd"]


def test_spawn_pty_unix_smoke() -> None:
    from pathlib import Path

    pty = pty_backend.spawn_pty(["/bin/sh"], str(Path.cwd()), 80, 24)
    try:
        assert pty.is_alive() is True
        assert isinstance(pty.fd, int)
        # The loop reads this fd directly; a blocking fd + spurious wakeup
        # would park the whole server (see notes/05-lessons-learned.md).
        assert os.get_blocking(pty.fd) is False
    finally:
        pty.terminate()
