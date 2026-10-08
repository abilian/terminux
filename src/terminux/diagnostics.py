"""Runtime diagnostics: event-loop watchdog + slow-operation timer.

The watchdog runs in its own daemon thread so it still wakes up when the
asyncio loop is wedged (the exact state the user is trying to debug).
The asyncio loop bumps a shared heartbeat every ~500 ms; if the watchdog
sees a heartbeat older than ``STALL_THRESHOLD`` it logs at WARNING and
prints every thread's Python stack via ``faulthandler.dump_traceback``
— giving the same evidence a manual ``kill -INFO <pid>`` would, only
fired automatically the moment the loop hangs.

Module-level state is intentional: only one watchdog thread per process,
and the heartbeat is published once and read from anywhere.
"""

from __future__ import annotations

import contextlib
import enum
import faulthandler
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

log = logging.getLogger(__name__)

# The asyncio loop is expected to bump this monotonic timestamp at least
# twice a second; if more than this many seconds pass without a bump, the
# watchdog assumes the loop is dead.
STALL_THRESHOLD = 3.0
# Don't spam the log every second of a sustained stall.
WARN_INTERVAL = 10.0
# How long the watchdog sleeps between checks.
POLL_INTERVAL = 1.0
# Operations slower than this are logged at WARNING; faster ones at DEBUG.
SLOW_OP_THRESHOLD = 0.2


class _WatchdogState:
    """Class-level mutable state lets us avoid the ``global`` statement —
    ``_WatchdogState.last_beat = …`` doesn't trip ``PLW0603``, and
    assignment to a class attribute is atomic in CPython.
    """

    last_beat: float = time.monotonic()
    started: bool = False


_start_lock = threading.Lock()


def beat() -> None:
    """Record a heartbeat — the asyncio loop is alive at this moment."""
    _WatchdogState.last_beat = time.monotonic()


def start_watchdog() -> None:
    """Spawn the watchdog thread (idempotent)."""
    with _start_lock:
        if _WatchdogState.started:
            return
        _WatchdogState.started = True
    beat()  # avoid a spurious warning before the first real heartbeat
    thread = threading.Thread(
        target=_run_watchdog,
        name="terminux-loop-watchdog",
        daemon=True,
    )
    thread.start()


class Finding(enum.Enum):
    """What a stale heartbeat means, as judged by the watchdog."""

    # The whole process got no CPU (the watchdog was frozen too): App
    # Nap, heavy swapping, a debugger. Stacks would show innocent frames.
    SUSPENDED = "suspended"
    # The loop missed its heartbeat while the process was running: a real
    # stall worth a stack dump.
    STALLED = "stalled"


@dataclass
class _Monitor:
    """Tells a stalled event loop from a process that wasn't scheduled.

    Both leave the heartbeat stale. The watchdog distinguishes them by its
    own lateness: if it overslept by more than ``STALL_THRESHOLD``, every
    thread was frozen, not just the loop. A stall is then measured only
    over time the process actually ran, so a resumed loop gets a fresh
    ``STALL_THRESHOLD`` to beat again before it is blamed.
    """

    resumed_at: float = float("-inf")
    last_warned: float = float("-inf")

    def observe(
        self, *, slept_at: float, now: float, last_beat: float
    ) -> tuple[Finding, float] | None:
        """Judge one wake-up; return a finding and its seconds, or None."""
        overslept = now - slept_at - POLL_INTERVAL
        if overslept >= STALL_THRESHOLD:
            self.resumed_at = now
            return Finding.SUSPENDED, overslept
        stalled_for = now - max(last_beat, self.resumed_at)
        if stalled_for < STALL_THRESHOLD or now - self.last_warned < WARN_INTERVAL:
            return None
        self.last_warned = now
        return Finding.STALLED, stalled_for


def _run_watchdog() -> None:
    monitor = _Monitor()
    while True:
        slept_at = time.monotonic()
        time.sleep(POLL_INTERVAL)
        result = monitor.observe(
            slept_at=slept_at,
            now=time.monotonic(),
            last_beat=_WatchdogState.last_beat,
        )
        if result is None:
            continue
        finding, seconds = result
        if finding is Finding.SUSPENDED:
            log.info(
                "process got no CPU for %.1fs (App Nap, heavy swapping, or a "
                "debugger); not an event-loop stall",
                seconds,
            )
            continue
        log.warning(
            "event loop unresponsive for %.1fs — dumping per-thread stacks "
            "(send SIGINFO/SIGUSR1 for additional dumps)",
            seconds,
        )
        with contextlib.suppress(Exception):
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


@contextlib.contextmanager
def time_op(name: str) -> Iterator[None]:
    """Log slow operations at WARNING (or all of them when --trace is on).

    Use around any synchronous I/O whose stall would freeze the server:
    ``with time_op("save_state"): save_state(...)``.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        if elapsed >= SLOW_OP_THRESHOLD:
            log.warning("slow %s: %.0fms", name, elapsed * 1000)
        elif log.isEnabledFor(logging.DEBUG):
            log.debug("%s: %.1fms", name, elapsed * 1000)
