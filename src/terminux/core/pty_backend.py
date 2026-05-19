"""PTY backend abstraction.

Unix is implemented via ``ptyprocess``. Windows (``pywinpty``/ConPTY) is a
future addition behind this same Protocol — see technical spec §10.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess  # noqa: S404  (fixed argv to `lsof`, no shell, resolved path)
import sys
from pathlib import Path
from typing import Protocol, cast, runtime_checkable


@runtime_checkable
class PtyBackend(Protocol):
    """OS-agnostic PTY interface used by ``core.terminal``."""

    @property
    def fd(self) -> int: ...

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
        self._proc = PtyProcess.spawn(
            argv,
            cwd=cwd,
            env=env,
            dimensions=(rows, cols),
        )

    @property
    def fd(self) -> int:
        return int(self._proc.fd)

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
    lsof = shutil.which("lsof")
    if lsof is None:
        return None
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
