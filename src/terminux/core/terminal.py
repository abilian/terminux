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
import time
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

# An OSC 133;D close is only treated as a "ready" attention signal when the
# command between the matching ;C and ;D took at least this long — otherwise
# every `cd` in a background tab would ring the sidebar.
OSC133_MIN_COMMAND_SECONDS = 2.0

# Single-byte control codes the attention scanner inspects.
_BEL = 0x07
_ESC_BYTE = 0x1B
_OSC_INTRO = 0x5D  # ']' — second byte of the ESC ] (OSC) introducer
_OSC_HEAD_MAX = 16  # how much of an OSC's params we capture for matching


class _AttentionScanner:
    """Stateful per-Terminal scanner for the three real "attention" signals.

    A naive ``b"\\x07" in data`` check trips on every OSC string terminator
    (the BEL byte also ends ``OSC 0/2;<title>\\x07`` title updates that tools
    like Claude Code emit constantly), so we walk the stream and only count
    a BEL that occurs *outside* an OSC. We also pick out:

    - ``OSC 9;<msg>`` — the iTerm2 desktop-notification convention.
    - ``OSC 133;D[;exit]`` — shell-integration "command finished", gated by
      a minimum command duration via the prior matching ``OSC 133;C``.

    The state survives across reads, so an OSC spanning a chunk boundary
    is still parsed correctly.
    """

    _GROUND = 0
    _ESC = 1
    _OSC = 2

    def __init__(self) -> None:
        self._state = self._GROUND
        # First ~16 bytes of the current OSC's parameters — enough to tell
        # ``9;``, ``133;C`` and ``133;D[;…]`` apart.
        self._osc_head = bytearray()
        self._command_start: float | None = None
        # Once we've seen *any* OSC 133 sequence we trust the shell's
        # own command boundaries over the os.tcgetpgrp() heuristic.
        self._osc133_seen = False
        # True between a matching OSC 133;C and 133;D, used for the
        # sidebar "working/ready" cue.
        self._in_command = False

    def feed(self, data: bytes, now: float) -> bool:
        """Scan ``data``; return True iff an attention signal fired."""
        state = self._state
        head = self._osc_head
        fired = False
        for b in data:
            if state == self._GROUND:
                if b == _ESC_BYTE:
                    state = self._ESC
                elif b == _BEL:  # standalone BEL → real "ding"
                    fired = True
            elif state == self._ESC:
                if b == _OSC_INTRO:
                    state = self._OSC
                    head.clear()
                else:
                    # Any other byte ends the ESC sequence (the trailing
                    # '\\' of a String Terminator falls here too).
                    state = self._GROUND
            elif b in {_BEL, _ESC_BYTE}:  # _OSC terminator (BEL or ST start)
                if self._osc_should_fire(now):
                    fired = True
                head.clear()
                state = self._ESC if b == _ESC_BYTE else self._GROUND
            elif len(head) < _OSC_HEAD_MAX:
                head.append(b)
        self._state = state
        return fired

    def _osc_should_fire(self, now: float) -> bool:
        head = bytes(self._osc_head)
        if head.startswith(b"9;"):
            return True
        if head.startswith(b"133;"):
            self._osc133_seen = True
            if head.startswith(b"133;C"):
                # Mark the start of a command; never fires by itself.
                self._command_start = now
                self._in_command = True
                return False
            if head.startswith(b"133;D"):
                self._in_command = False
                start = self._command_start
                self._command_start = None
                return start is not None and (now - start) >= OSC133_MIN_COMMAND_SECONDS
            # OSC 133;A (prompt start) / 133;B (prompt end) — both mean
            # "shell is back at a prompt", definitely not in a command.
            self._in_command = False
        return False

    @property
    def osc133_seen(self) -> bool:
        """True once the shell has emitted any OSC 133 sequence."""
        return self._osc133_seen

    @property
    def in_command(self) -> bool:
        """True between a matching OSC 133;C and 133;D (or until the next
        OSC 133;A / ;B). Only meaningful when ``osc133_seen`` is true."""
        return self._in_command


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
        self._attention = _AttentionScanner()
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
        # OSC-aware: only a real BEL (outside any OSC), OSC 9, or a long-
        # enough OSC 133;D counts as attention — title-bar updates carry a
        # trailing BEL we deliberately ignore. The scanner is always fed
        # (regardless of on_attention) so its OSC 133 state stays current
        # for is_busy() / the sidebar working/ready cue.
        fired = self._attention.feed(data, time.monotonic())
        if fired and self.on_attention is not None:
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

    def is_busy(self) -> bool:
        """True if a foreground task is running in this terminal right now.

        Prefers OSC 133 (shell integration) — between ``;C`` and ``;D`` the
        shell *is* running a command. With no shell integration, falls back
        to comparing ``tcgetpgrp(fd)`` with the shell's own pid: if some
        other process group is foregrounded, the shell has spawned a child
        that is currently in the foreground. Defensive against closed fds
        and exited shells.
        """
        if self._exited:
            return False
        scanner = self._attention
        if scanner.osc133_seen:
            return scanner.in_command
        try:
            fg = os.tcgetpgrp(self._pty.fd)
        except OSError:
            return False
        return fg > 0 and fg != self._pty.pid

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
