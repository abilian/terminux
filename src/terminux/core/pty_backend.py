"""PTY backend abstraction.

Unix is implemented via ``ptyprocess``, Windows via ``pywinpty`` (ConPTY).
Both push output to the event loop through ``attach``; see
``notes/06-windows-port.md`` for why reading lives in the backend.
"""

from __future__ import annotations

import codecs
import contextlib
import ctypes
import ctypes.util
import functools
import logging
import os
import select
import shutil
import signal
import subprocess  # noqa: S404  (fixed argv to `lsof`, no shell, resolved path)
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from terminux.diagnostics import time_op

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

log = logging.getLogger(__name__)

READ_CHUNK = 65536


class PtyBackend(Protocol):
    """OS-agnostic PTY interface used by ``core.terminal``."""

    @property
    def pid(self) -> int: ...

    def attach(
        self, loop: asyncio.AbstractEventLoop, on_data: Callable[[bytes], None]
    ) -> None:
        """Start delivering output to ``on_data`` on the loop thread.

        ``b""`` means EOF and is delivered at most once. Must be called on
        the loop thread.
        """

    def detach(self) -> None:
        """Stop delivering output (idempotent, loop thread)."""

    def foreground_busy(self) -> bool | None:
        """Kernel-level "a command is running" guess; None = can't tell."""

    def write(self, data: bytes) -> None: ...

    def resize(self, cols: int, rows: int) -> None: ...

    def terminate(self) -> None: ...

    def exit_code(self) -> int | None: ...

    def cwd(self) -> str | None: ...


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("TERM", "xterm-256color")
    env["TERMINUX"] = "1"
    # Lets shell-init snippets (OSC 133 integration, etc.) guard their
    # setup on the host terminal — matches the iTerm2/Ghostty/wezterm
    # convention.
    env["TERM_PROGRAM"] = "terminux"
    return env


class UnixPty:
    """PTY-backed child process for POSIX systems."""

    def __init__(self, argv: list[str], cwd: str, cols: int, rows: int) -> None:
        from ptyprocess import PtyProcess  # noqa: PLC0415  (optional/heavy import)

        self._proc = PtyProcess.spawn(
            argv,
            cwd=cwd,
            env=_child_env(),
            dimensions=(rows, cols),
        )
        # The master fd must never park a thread inside the kernel: the
        # asyncio loop reads it directly (a spurious kqueue wakeup on a
        # blocking fd would freeze the whole server — observed in the
        # field), and ``write`` below handles EAGAIN itself.
        os.set_blocking(self._proc.fd, False)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_data: Callable[[bytes], None] | None = None

    @property
    def fd(self) -> int:
        return int(self._proc.fd)

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def attach(
        self, loop: asyncio.AbstractEventLoop, on_data: Callable[[bytes], None]
    ) -> None:
        # No thread per PTY: the loop's selector watches the master fd.
        self._loop = loop
        self._on_data = on_data
        loop.add_reader(self.fd, self._on_readable)

    def detach(self) -> None:
        loop, self._loop = self._loop, None
        self._on_data = None
        if loop is not None:
            with contextlib.suppress(OSError, ValueError):
                loop.remove_reader(self.fd)

    def _on_readable(self) -> None:
        on_data = self._on_data
        if on_data is None:
            return
        try:
            data = os.read(self.fd, READ_CHUNK)
        except BlockingIOError:
            return  # spurious wakeup; fd is non-blocking, nothing to read
        except OSError:
            data = b""  # EIO on Linux when the child exits
        if not data:
            self.detach()
        on_data(data)

    def foreground_busy(self) -> bool | None:
        """True when the tty's foreground process group isn't the shell's."""
        try:
            fg = os.tcgetpgrp(self.fd)
        except OSError:
            return None
        return fg > 0 and fg != self.pid

    def write(self, data: bytes) -> None:
        fd = self._proc.fd
        view = memoryview(data)
        with contextlib.suppress(OSError):
            while view:
                try:
                    n = os.write(fd, view)
                except BlockingIOError:
                    # Kernel input queue full (large paste into a program
                    # that isn't reading). Runs on a worker thread (see
                    # server ``_pump_in``), so waiting parks only this
                    # terminal's writer, never the loop.
                    select.select([], [fd], [])
                    continue
                view = view[n:]

    def resize(self, cols: int, rows: int) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._proc.setwinsize(rows, cols)

    def is_alive(self) -> bool:
        return bool(self._proc.isalive())

    def terminate(self) -> None:
        """Hang up, then escalate (functional spec §10).

        ptyprocess's ``close(force=True)`` closes the master (the kernel
        sends the shell SIGHUP, so it can save its history), then sends
        SIGHUP, SIGCONT, SIGINT and finally SIGKILL, waiting a moment and
        stopping as soon as the child is gone. Those waits add up to about
        half a second, so they run on a thread: callers include the event
        loop, which must never sleep.
        """
        if not self._proc.isalive():
            return
        threading.Thread(
            target=self._proc.close,
            kwargs={"force": True},
            name=f"pty-hangup-{self.pid}",
            daemon=True,
        ).start()

    def exit_code(self) -> int | None:
        if self._proc.isalive():
            return None
        try:
            self._proc.wait()
        except Exception:  # noqa: BLE001  (best-effort reap)
            return None
        return cast("int | None", self._proc.exitstatus)

    def cwd(self) -> str | None:
        """Best-effort current directory of the shell process.

        Lets a new tab open where the previously active shell was, without
        requiring shell-side OSC 7 configuration.
        """
        if sys.platform == "linux":
            return _linux_cwd(self.pid)
        if sys.platform == "darwin":
            return _darwin_cwd(self.pid)
        return None


def _linux_cwd(pid: int) -> str | None:
    with contextlib.suppress(OSError):
        return str(Path(f"/proc/{pid}/cwd").readlink())
    return None


def _darwin_cwd(pid: int) -> str | None:
    """Return ``pid``'s current working directory on macOS.

    Uses ``libproc.proc_pidinfo(PROC_PIDVNODEPATHINFO)`` — a pure kernel
    call that's fast (microseconds) and crucially cannot hang on a wedged mount,
    unlike ``lsof`` which traverses every file descriptor and can stall
    indefinitely in D-state when one of those fds points at a sick volume
    (a deadlock that wedges the whole server, since ``cwd()`` is called
    under ``AppController.lock``). Falls back to ``lsof`` only if libproc
    is unavailable for some unusual reason — not when the call fails (a
    zombie shell, EPERM after ``exec sudo -s``), which would bring lsof
    back under the lock exactly when the process is in a strange state.
    """
    if _proc_pidinfo is None:
        return _lsof_cwd(pid)
    return _libproc_cwd(pid)


# --- libproc (preferred path) ----------------------------------------

# Selector for ``struct proc_vnodepathinfo`` — see <sys/proc_info.h>.
_PROC_PIDVNODEPATHINFO = 9
# ``proc_vnodepathinfo`` layout: two ``vnode_info_path`` structs (cwd, then
# root). Each ``vnode_info_path`` is ``struct vnode_info`` (152 B; see
# offsetof(vnode_info_path, vip_path)) followed by ``char vip_path[MAXPATHLEN]``
# (1024 B). Total struct size is 2 * (152 + 1024) = 2352 B.
_VNODE_INFO_SIZE = 152
_MAXPATHLEN = 1024
_VNODEPATHINFO_SIZE = 2 * (_VNODE_INFO_SIZE + _MAXPATHLEN)


def _load_proc_pidinfo() -> Callable[..., int] | None:
    """Resolve ``proc_pidinfo`` once at import; ``None`` if unavailable."""
    lib_name = ctypes.util.find_library("c")
    if lib_name is None:
        return None
    try:
        libc = ctypes.CDLL(lib_name, use_errno=True)
        fn = libc.proc_pidinfo
    except (OSError, AttributeError):
        return None
    fn.argtypes = [
        ctypes.c_int,  # pid
        ctypes.c_int,  # flavor
        ctypes.c_uint64,  # arg
        ctypes.c_void_p,  # buffer
        ctypes.c_int,  # buffersize
    ]
    fn.restype = ctypes.c_int
    return cast("Callable[..., int]", fn)


_proc_pidinfo: Callable[..., int] | None = (
    _load_proc_pidinfo() if sys.platform == "darwin" else None
)


def _libproc_cwd(pid: int) -> str | None:
    fn = _proc_pidinfo
    if fn is None:
        return None
    buf = ctypes.create_string_buffer(_VNODEPATHINFO_SIZE)
    with time_op(f"libproc_cwd[{pid}]"):
        try:
            n = fn(pid, _PROC_PIDVNODEPATHINFO, 0, buf, _VNODEPATHINFO_SIZE)
        except OSError:
            return None
    if n <= 0:
        return None
    # Slice out the cwd path: it begins at offset ``_VNODE_INFO_SIZE`` within
    # the buffer and is a NUL-terminated C string up to MAXPATHLEN bytes.
    path_bytes = buf.raw[_VNODE_INFO_SIZE : _VNODE_INFO_SIZE + _MAXPATHLEN]
    null = path_bytes.find(b"\x00")
    if null == 0:
        return None
    if null > 0:
        path_bytes = path_bytes[:null]
    try:
        return path_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


# --- lsof (fallback path) --------------------------------------------


def _lsof_cwd(pid: int) -> str | None:
    lsof = shutil.which("lsof")
    if lsof is None:
        return None
    with time_op(f"lsof_cwd[{pid}]"):
        try:
            result = subprocess.run(  # noqa: S603  (fixed argv, resolved path, no shell)
                [lsof, "-a", "-d", "cwd", "-p", str(pid), "-Fn"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


# --- Windows (ConPTY via pywinpty) -------------------------------------

# ConPTY asks the terminal for its Primary Device Attributes at startup and
# holds the child up to 3 s for the answer. We answer it right away, as
# xterm.js would, and drop the query from the stream: otherwise each
# backlog replay (a second window, a reconnect) would answer it again,
# into the shell's input.
_CONPTY_DA1_QUERY = "\x1b[c"
_DA1_REPLY = "\x1b[?1;2c"
_STARTUP_WINDOW = 256  # chars of output in which to expect the query


class WindowsPty:
    """ConPTY-backed child process, through ``pywinpty``'s low-level ``PTY``.

    ConPTY hands out pipes, which neither ``select`` nor the Proactor loop's
    (missing) ``add_reader`` can watch, so a daemon thread per terminal does
    the blocking reads and posts the bytes to the loop. pywinpty decodes
    ConPTY's UTF-8 itself (multibyte characters split across reads come out
    whole) and takes ``str`` on write; bytes stay the currency everywhere
    else, so both directions convert here.

    A blocking read can't be trusted to end when the shell exits (if the
    shell is gone before the first read, it never returns: the output pipe
    lives as long as the pseudo console). So a second thread waits on the
    shell's process handle and, once it exits, wakes the reader with
    ``cancel_io`` until it has drained what's left and stopped.

    The reader thread also owns the final release of the ``PTY`` object:
    dropping it calls ``ClosePseudoConsole``, which can block and which
    takes down the console-attached children (``Start-Job``, ``start /b``)
    — but not the ones with a window of their own (``Start-Process``),
    the same as closing a Windows Terminal tab.
    """

    def __init__(self, argv: list[str], cwd: str, cols: int, rows: int) -> None:
        from winpty import PTY  # noqa: PLC0415  (Windows-only dependency)

        env = _child_env()
        exe = shutil.which(argv[0], path=env.get("PATH")) or argv[0]
        # pywinpty appends ``cmdline`` to the quoted executable path.
        cmdline = " " + subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else None
        env_block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        pty = PTY(cols, rows)
        try:
            started = pty.spawn(exe, cmdline=cmdline, cwd=cwd, env=env_block)
        except Exception as e:  # WinptyError, e.g. no such file
            msg = f"could not start {exe}: {e}"
            raise OSError(msg) from e
        if not started or pty.pid is None:
            msg = f"could not start {exe}"
            raise OSError(msg)
        self._pty: Any = pty  # None once released (see ``_release``)
        self._pid = int(pty.pid)
        self._exit_status: int | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._write_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._child_exited = threading.Event()
        self._startup_seen: int | None = 0  # None once the query is handled
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_data: Callable[[bytes], None] | None = None

    @property
    def pid(self) -> int:
        return self._pid

    def attach(
        self, loop: asyncio.AbstractEventLoop, on_data: Callable[[bytes], None]
    ) -> None:
        self._loop = loop
        self._on_data = on_data
        self._reader = threading.Thread(
            target=self._read_loop, name=f"pty-reader-{self._pid}", daemon=True
        )
        self._reader.start()
        threading.Thread(
            target=self._watch_exit, name=f"pty-exit-{self._pid}", daemon=True
        ).start()

    def detach(self) -> None:
        self._on_data = None
        pty = self._pty
        if pty is not None:
            # Wakes a blocked read; the thread then sees ``_on_data`` gone.
            # (If the read wasn't blocked yet, the exit watcher wakes it
            # once ``terminate`` has ended the shell.)
            with contextlib.suppress(Exception):
                pty.cancel_io()

    def _read_loop(self) -> None:
        pty = self._pty
        while self._on_data is not None:
            if self._child_exited.is_set():
                self._post(_drain_nonblocking(pty).encode("utf-8"))
                break
            try:
                text = pty.read(blocking=True)
                # ConPTY emits in small pieces; coalesce what's already
                # there into one loop callback.
                if text:
                    text += _drain_nonblocking(pty, READ_CHUNK - len(text))
            except Exception:  # noqa: BLE001  (WinptyError: EOF, cancelled, closed)
                if self._child_exited.is_set():
                    continue  # woken by the exit watcher: drain, then stop
                break
            if text and self._startup_seen is not None:
                text = self._answer_startup_query(text)
            if text:
                self._post(text.encode("utf-8"))
            elif pty.iseof():
                break
        if self._child_exited.is_set():
            # Before EOF reaches the loop, which asks for the exit code.
            with contextlib.suppress(Exception):
                self._exit_status = pty.get_exitstatus()
        self._post(b"")
        del pty
        self._release()

    def _answer_startup_query(self, text: str) -> str:
        if _CONPTY_DA1_QUERY in text:
            self._startup_seen = None
            self.write(_DA1_REPLY.encode())
            return text.replace(_CONPTY_DA1_QUERY, "", 1)
        seen = (self._startup_seen or 0) + len(text)
        self._startup_seen = seen if seen < _STARTUP_WINDOW else None
        return text

    def _watch_exit(self) -> None:
        _wait_for_process(self._pid, self.is_alive)
        self._child_exited.set()
        reader = self._reader
        while reader is not None and reader.is_alive():
            pty = self._pty
            if pty is not None:
                with contextlib.suppress(Exception):
                    pty.cancel_io()
            # Repeated: a cancel only wakes a read already in progress.
            reader.join(0.1)

    def _post(self, data: bytes) -> None:
        on_data, loop = self._on_data, self._loop
        if on_data is None or loop is None:
            return
        if not data:
            self._on_data = None  # EOF is delivered once
        with contextlib.suppress(RuntimeError):  # loop already closed
            loop.call_soon_threadsafe(on_data, data)

    def _release(self) -> None:
        """Drop the PTY, closing the pseudo console (may block)."""
        pty = self._pty
        if pty is None:
            return
        if self._exit_status is None:
            with contextlib.suppress(Exception):
                self._exit_status = pty.get_exitstatus()
        self._pty = None

    def foreground_busy(self) -> bool | None:
        """True when the shell has a child process: without process groups,
        that's the closest thing to "a command is in the foreground"."""
        return _win_has_child(self._pid)

    def write(self, data: bytes) -> None:
        with self._write_lock:
            text = self._decoder.decode(data)
            pty = self._pty
            if text and pty is not None:
                with contextlib.suppress(Exception):
                    pty.write(text)

    def resize(self, cols: int, rows: int) -> None:
        pty = self._pty
        if pty is not None:
            with contextlib.suppress(Exception):
                pty.set_size(cols, rows)

    def is_alive(self) -> bool:
        pty = self._pty
        if pty is None:
            return False
        try:
            return bool(pty.isalive())
        except Exception:  # noqa: BLE001
            return False

    def terminate(self) -> None:
        self.detach()
        if self.is_alive():
            with contextlib.suppress(OSError):
                os.kill(self._pid, signal.SIGTERM)  # TerminateProcess
        if self._reader is None:
            # Never attached (the tab closed while spawning): nobody else
            # will release the console, and that may block — off-thread.
            threading.Thread(target=self._release, daemon=True).start()

    def exit_code(self) -> int | None:
        pty = self._pty
        if pty is None or self._exit_status is not None:
            return self._exit_status
        try:
            if pty.isalive():
                return None
            status = pty.get_exitstatus()
        except Exception:  # noqa: BLE001
            return None
        return None if status is None else int(status)

    def cwd(self) -> str | None:  # noqa: PLR6301  (PtyBackend method)
        # No supported API reads another process's cwd on Windows; the
        # shell reports it instead (OSC 7 / 9;9, see ``core.terminal``).
        return None


class _Readable(Protocol):
    def read(self, blocking: bool = False) -> str: ...


def _drain_nonblocking(pty: _Readable, limit: int = READ_CHUNK) -> str:
    """Whatever output is already buffered, without waiting for more."""
    parts: list[str] = []
    size = 0
    with contextlib.suppress(Exception):  # WinptyError once the pipe is done
        while size < limit:
            more = pty.read(blocking=False)
            if not more:
                break
            parts.append(more)
            size += len(more)
    return "".join(parts)


_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF


def _wait_for_process(pid: int, is_alive: Callable[[], bool]) -> None:
    """Block until process ``pid`` exits.

    Waits on its handle; polls ``is_alive`` if no handle can be opened.
    """
    handle = None
    if sys.platform == "win32":
        handle = _kernel32().OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        while is_alive():
            time.sleep(0.5)
        return
    kernel32 = _kernel32()
    try:
        kernel32.WaitForSingleObject(handle, _INFINITE)
    finally:
        kernel32.CloseHandle(handle)


class _ProcessEntry32(ctypes.Structure):
    _fields_ = (
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    )


_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@functools.cache
def _kernel32() -> ctypes.CDLL:
    if sys.platform != "win32":
        msg = "kernel32 is Windows-only"
        raise OSError(msg)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # pyrefly: ignore[missing-attribute]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    return kernel32


def _win_has_child(pid: int) -> bool | None:
    """Whether any process has ``pid`` as its parent (Toolhelp snapshot).

    Cheap enough for the ~1 Hz busy poll (one snapshot, a few hundred
    entries). The shell is alive, so its pid can't have been reused.
    """
    if sys.platform != "win32":
        return None
    kernel32 = _kernel32()
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap is None or snap == _INVALID_HANDLE_VALUE:
        return None
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == pid and entry.th32ProcessID != pid:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


def spawn_pty(argv: list[str], cwd: str, cols: int, rows: int) -> PtyBackend:
    if sys.platform == "win32":
        return WindowsPty(argv, cwd, cols, rows)
    return UnixPty(argv, cwd, cols, rows)
