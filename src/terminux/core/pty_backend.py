"""PTY backend abstraction.

Unix is implemented via ``ptyprocess``. Windows (``pywinpty``/ConPTY) is a
future addition behind this same Protocol — see technical spec §10.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import logging
import os
import shutil
import signal
import subprocess  # noqa: S404  (fixed argv to `lsof`, no shell, resolved path)
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from terminux.diagnostics import time_op

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)


@runtime_checkable
class PtyBackend(Protocol):
    """OS-agnostic PTY interface used by ``core.terminal``."""

    @property
    def fd(self) -> int: ...

    @property
    def pid(self) -> int: ...

    def write(self, data: bytes) -> None: ...

    def resize(self, cols: int, rows: int) -> None: ...

    def is_alive(self) -> bool: ...

    def terminate(self) -> None: ...

    def exit_code(self) -> int | None: ...

    def cwd(self) -> str | None: ...


class UnixPty:
    """PTY-backed child process for POSIX systems."""

    def __init__(self, argv: list[str], cwd: str, cols: int, rows: int) -> None:
        from ptyprocess import PtyProcess  # noqa: PLC0415  (optional/heavy import)

        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env["TERMINUX"] = "1"
        # Lets shell-init snippets (OSC 133 integration, etc.) guard their
        # setup on the host terminal — matches the iTerm2/Ghostty/wezterm
        # convention.
        env["TERM_PROGRAM"] = "terminux"
        self._proc = PtyProcess.spawn(
            argv,
            cwd=cwd,
            env=env,
            dimensions=(rows, cols),
        )

    @property
    def fd(self) -> int:
        return int(self._proc.fd)

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def write(self, data: bytes) -> None:
        with contextlib.suppress(OSError):
            os.write(self._proc.fd, data)

    def resize(self, cols: int, rows: int) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._proc.setwinsize(rows, cols)

    def is_alive(self) -> bool:
        return bool(self._proc.isalive())

    def terminate(self) -> None:
        """SIGHUP → SIGTERM → SIGKILL escalation (functional spec §10)."""
        if not self._proc.isalive():
            return
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
            try:
                self._proc.kill(sig)
            except OSError:
                return
            if not self._proc.isalive():
                return

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

        Lets a new tab open where the previously active shell was (cmux
        behaviour), without requiring shell-side OSC 7 configuration.
        """
        pid = self._proc.pid
        if pid is None:
            return None
        if sys.platform == "linux":
            return _linux_cwd(pid)
        if sys.platform == "darwin":
            return _darwin_cwd(pid)
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
    is unavailable for some unusual reason.
    """
    cwd = _libproc_cwd(pid)
    if cwd is not None:
        return cwd
    return _lsof_cwd(pid)


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


def spawn_pty(argv: list[str], cwd: str, cols: int, rows: int) -> PtyBackend:
    if sys.platform == "win32":
        msg = "Windows PTY backend is not implemented yet (technical spec §10)."
        raise NotImplementedError(msg)
    return UnixPty(argv, cwd, cols, rows)
