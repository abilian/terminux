"""A live terminal: a PTY child plus bounded, batched output fan-out.

The reader is registered with the asyncio event loop (no thread-per-PTY).
Each subscriber has a bounded pending buffer flushed on a short coalescing
interval (terax's batched-flush pattern); if a slow consumer falls more than
``OUTBOUND_CAP`` behind, its buffer is dropped and a one-shot notice is sent
so a runaway process can never freeze the UI or grow memory unbounded
(technical spec §3.3, functional spec §10). A separate, smaller backlog is
retained so a (re)connecting WebSocket gets recent scrollback.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from typing import TYPE_CHECKING

from terminux.core.pty_backend import PtyBackend, spawn_pty

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

BACKLOG_CAP = 512 * 1024  # bytes retained for replay on (re)connect
OUTBOUND_CAP = 4 * 1024 * 1024  # per-subscriber pending cap before drop
FLUSH_INTERVAL = 0.008  # seconds to coalesce a burst into one WS frame
READ_CHUNK = 65536


class Subscriber:
    """A bounded, batched view of a terminal's output for one consumer."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._dropped = False
        self._closed = False
        self._event = asyncio.Event()

    def feed(self, data: bytes) -> None:
        if self._closed:
            return
        if len(self._pending) + len(data) > OUTBOUND_CAP:
            # Consumer fell too far behind: discard the backlog, keep only
            # the most recent tail, and flag a one-shot drop notice.
            self._dropped = True
            self._pending.clear()
            self._pending += data[-OUTBOUND_CAP:]
        else:
            self._pending += data
        self._event.set()

    def close(self) -> None:
        self._closed = True
        self._event.set()

    async def drain(self) -> tuple[bool, bytes, bool]:
        """Wait for output, coalesce a burst, return (dropped, data, closed)."""
        await self._event.wait()
        if not self._closed:
            await asyncio.sleep(FLUSH_INTERVAL)  # batch a burst
        self._event.clear()
        dropped, self._dropped = self._dropped, False
        data = bytes(self._pending)
        self._pending.clear()
        return dropped, data, self._closed


class Terminal:
    """Owns one PTY child and fans its output out to subscribers."""

    def __init__(
        self, argv: list[str], cwd: str, cols: int = 80, rows: int = 24
    ) -> None:
        self.id = uuid.uuid4().hex
        self._pty: PtyBackend = spawn_pty(argv, cwd, cols, rows)
        self._loop = asyncio.get_running_loop()
        self._backlog = bytearray()
        self._subscribers: set[Subscriber] = set()
        self._exited = False
        self._exit_code: int | None = None
        self.on_activity: Callable[[], None] | None = None
        self.on_attention: Callable[[], None] | None = None
        self.on_exit: Callable[[int | None], None] | None = None
        self._loop.add_reader(self._pty.fd, self._on_readable)

    # ----- reading ------------------------------------------------------

    def _on_readable(self) -> None:
        try:
            data = os.read(self._pty.fd, READ_CHUNK)
        except OSError:
            data = b""  # EIO on Linux when the child exits
        if not data:
            self._handle_eof()
            return
        self._backlog += data
        if len(self._backlog) > BACKLOG_CAP:
            del self._backlog[: len(self._backlog) - BACKLOG_CAP]
        for sub in self._subscribers:
            sub.feed(data)
        if self.on_activity is not None:
            self.on_activity()
        # BEL or an OSC 9 desktop notification → the task wants attention.
        if self.on_attention is not None and (b"\x07" in data or b"\x1b]9;" in data):
            self.on_attention()

    def _handle_eof(self) -> None:
        if self._exited:
            return
        self._exited = True
        with contextlib.suppress(OSError, ValueError):
            self._loop.remove_reader(self._pty.fd)
        self._exit_code = self._pty.exit_code()
        for sub in self._subscribers:
            sub.close()
        if self.on_exit is not None:
            self.on_exit(self._exit_code)

    # ----- subscriptions ------------------------------------------------

    def subscribe(self) -> Subscriber:
        """Register a subscriber; it first receives the replayed backlog."""
        sub = Subscriber()
        if self._backlog:
            sub.feed(bytes(self._backlog))
        if self._exited:
            sub.close()
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)

    # ----- control ------------------------------------------------------

    def write(self, data: bytes) -> None:
        if not self._exited:
            self._pty.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if not self._exited:
            self._pty.resize(cols, rows)

    def cwd(self) -> str | None:
        """Best-effort working directory of this terminal's shell."""
        return self._pty.cwd()

    @property
    def exited(self) -> bool:
        return self._exited

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def close(self) -> None:
        """Terminate the child and tear the terminal down."""
        with contextlib.suppress(OSError, ValueError):
            self._loop.remove_reader(self._pty.fd)
        self._pty.terminate()
        self._exited = True
        for sub in self._subscribers:
            sub.close()


class TerminalRegistry:
    """All live terminals, keyed by terminal id."""

    def __init__(self) -> None:
        self._terminals: dict[str, Terminal] = {}

    def create(self, argv: list[str], cwd: str, cols: int, rows: int) -> Terminal:
        term = Terminal(argv, cwd, cols, rows)
        self._terminals[term.id] = term
        return term

    def get(self, terminal_id: str) -> Terminal | None:
        return self._terminals.get(terminal_id)

    def close(self, terminal_id: str) -> None:
        term = self._terminals.pop(terminal_id, None)
        if term is not None:
            term.close()

    def close_all(self) -> None:
        for term in list(self._terminals.values()):
            term.close()
        self._terminals.clear()
