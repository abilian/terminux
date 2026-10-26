"""Deterministic unit tests for PTY backend helpers and branches.

These swap in a fake child process so terminate/exit_code/cwd branches are
exercised without depending on signals or the host OS.
"""

from __future__ import annotations

import os
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


unix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY")


def test_exit_code_none_while_alive() -> None:
    assert _unixpty(_FakeProc(alive_seq=[True])).exit_code() is None


def test_exit_code_value_and_wait_exception() -> None:
    assert _unixpty(_FakeProc(alive_seq=[False], exitstatus=7)).exit_code() == 7
    p = _FakeProc(alive_seq=[False])
    p.wait_raises = True
    assert _unixpty(p).exit_code() is None


def test_linux_cwd_handles_missing_proc() -> None:
    assert _linux_cwd(2_147_483_000) is None


def test_darwin_cwd_no_lsof(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend, "_proc_pidinfo", None)
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: None)
    assert _darwin_cwd(123) is None


def test_darwin_cwd_parses_lsof_output(monkeypatch) -> None:
    # No libproc at all: the only case that falls back to the lsof parser.
    monkeypatch.setattr(pty_backend, "_proc_pidinfo", None)
    monkeypatch.setattr(pty_backend.shutil, "which", lambda _n: "/usr/bin/lsof")

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(
            [], 0, stdout="p1\nfcwd\nn/var/tmp\n", stderr=""
        )

    monkeypatch.setattr(pty_backend.subprocess, "run", fake_run)
    assert _darwin_cwd(1) == "/var/tmp"


def test_darwin_cwd_no_match_and_error(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend, "_proc_pidinfo", None)
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


@pytest.mark.parametrize("libproc_result", ["/from/libproc", None])
def test_darwin_cwd_never_runs_lsof_when_libproc_exists(
    monkeypatch, libproc_result
) -> None:
    """lsof can hang on a sick volume and ``cwd()`` runs under the
    controller lock: with libproc present, even a failed call (zombie,
    EPERM) answers without it."""
    monkeypatch.setattr(pty_backend, "_proc_pidinfo", lambda *_a: 0)
    monkeypatch.setattr(pty_backend, "_libproc_cwd", lambda _pid: libproc_result)

    def boom(*_a, **_k):
        raise AssertionError("lsof fallback should not run")

    monkeypatch.setattr(pty_backend.shutil, "which", boom)
    assert _darwin_cwd(1) == libproc_result


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


@unix_only
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


# ----- UnixPty reading (attach / _on_readable / foreground_busy) ---------


class _FakeLoop:
    def __init__(self) -> None:
        self.readers: dict[int, object] = {}

    def add_reader(self, fd: int, cb: object) -> None:
        self.readers[fd] = cb

    def remove_reader(self, fd: int) -> None:
        self.readers.pop(fd, None)


def _attached(monkeypatch, read) -> tuple[UnixPty, _FakeLoop, list[bytes]]:
    p = _FakeProc()
    p.fd = 7
    pty = _unixpty(p)
    pty._loop = None  # type: ignore[attr-defined]
    pty._on_data = None  # type: ignore[attr-defined]
    loop = _FakeLoop()
    got: list[bytes] = []
    pty.attach(loop, got.append)  # type: ignore[arg-type]
    monkeypatch.setattr(pty_backend.os, "read", read)
    return pty, loop, got


def test_unixpty_reads_on_the_loop_and_detaches_at_eof(monkeypatch) -> None:
    chunks = [b"hello", b""]
    pty, loop, got = _attached(monkeypatch, lambda *_a: chunks.pop(0))
    assert 7 in loop.readers  # no thread: the loop watches the fd
    pty._on_readable()
    pty._on_readable()
    assert got == [b"hello", b""]
    assert loop.readers == {}  # EOF removed the reader
    pty._on_readable()  # a late wakeup after detach is ignored
    assert got == [b"hello", b""]


def test_unixpty_spurious_wakeup_is_noop(monkeypatch) -> None:
    def eagain(*_a: object) -> bytes:
        raise BlockingIOError

    pty, loop, got = _attached(monkeypatch, eagain)
    pty._on_readable()
    # EAGAIN is not EOF: the tab must stay open.
    assert got == []
    assert 7 in loop.readers


def test_unixpty_read_oserror_is_eof(monkeypatch) -> None:
    def eio(*_a: object) -> bytes:
        raise OSError  # EIO on Linux when the child exits

    pty, loop, got = _attached(monkeypatch, eio)
    pty._on_readable()
    assert got == [b""]
    assert loop.readers == {}
    pty.detach()  # idempotent


def test_unixpty_foreground_busy_compares_pgrp_to_shell(monkeypatch) -> None:
    pty = _unixpty(_FakeProc(pid=4242))
    pty._proc.fd = 7  # type: ignore[attr-defined]
    monkeypatch.setattr(pty_backend.os, "tcgetpgrp", lambda _fd: 4242, raising=False)
    assert pty.foreground_busy() is False  # the shell is in the foreground
    monkeypatch.setattr(pty_backend.os, "tcgetpgrp", lambda _fd: 9999, raising=False)
    assert pty.foreground_busy() is True

    def boom(_fd: int) -> int:
        raise OSError

    monkeypatch.setattr(pty_backend.os, "tcgetpgrp", boom, raising=False)
    assert pty.foreground_busy() is None  # can't tell


# ----- WindowsPty helpers -------------------------------------------------


class _FakeWinpty:
    def __init__(self, reads: list[object]) -> None:
        self._reads = reads

    def read(self, blocking: bool = False) -> str:
        item = self._reads.pop(0) if self._reads else ""
        if isinstance(item, Exception):
            raise item
        return str(item)


def test_drain_nonblocking_stops_at_empty_limit_or_error() -> None:
    assert pty_backend._drain_nonblocking(_FakeWinpty(["a", "b", "", "c"])) == "ab"
    assert (
        pty_backend._drain_nonblocking(_FakeWinpty(["aaa", "bbb", "c"]), 4) == "aaabbb"
    )
    pipe_done = _FakeWinpty(["a", RuntimeError("EOF"), "b"])
    assert pty_backend._drain_nonblocking(pipe_done) == "a"


def test_windowspty_answers_conpty_startup_query_once() -> None:
    pty = pty_backend.WindowsPty.__new__(pty_backend.WindowsPty)
    pty._startup_seen = 0  # type: ignore[attr-defined]
    written: list[bytes] = []
    pty.write = written.append  # type: ignore[method-assign]
    assert pty._answer_startup_query("\x1b[1t") == "\x1b[1t"
    assert pty._answer_startup_query("\x1b[c\x1b[?1004h") == "\x1b[?1004h"
    assert written == [b"\x1b[?1;2c"]
    assert pty._startup_seen is None  # handled: stop looking


def test_windowspty_stops_looking_after_the_startup_window() -> None:
    pty = pty_backend.WindowsPty.__new__(pty_backend.WindowsPty)
    pty._startup_seen = 0  # type: ignore[attr-defined]
    pty.write = lambda _d: None  # type: ignore[method-assign]
    pty._answer_startup_query("x" * pty_backend._STARTUP_WINDOW)
    assert pty._startup_seen is None


def test_wait_for_process_polls_without_a_handle(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend.sys, "platform", "linux")  # no OpenProcess
    monkeypatch.setattr(pty_backend.time, "sleep", lambda _s: None)
    alive = [True, True, False]
    pty_backend._wait_for_process(1, lambda: alive.pop(0))
    assert alive == []


@pytest.mark.skipif(sys.platform != "win32", reason="Toolhelp is Windows-only")
def test_win_has_child_sees_a_real_child() -> None:
    # Not sys.executable: a venv's python.exe is a launcher with a child.
    child = subprocess.Popen(
        ["ping", "-n", "30", "127.0.0.1"],  # noqa: S607
        stdout=subprocess.DEVNULL,
    )
    try:
        assert pty_backend._win_has_child(os.getpid()) is True
        assert pty_backend._win_has_child(child.pid) is False
    finally:
        child.kill()
        child.wait()


def test_win_has_child_is_unknown_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(pty_backend.sys, "platform", "linux")
    assert pty_backend._win_has_child(1) is None
