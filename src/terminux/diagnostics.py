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
import faulthandler
import logging
import sys
import threading
import time
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


def _run_watchdog() -> None:
    last_warned = 0.0
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        stalled_for = now - _WatchdogState.last_beat
        if stalled_for < STALL_THRESHOLD:
            continue
        if now - last_warned < WARN_INTERVAL:
            continue
        last_warned = now
        log.warning(
            "event loop unresponsive for %.1fs — dumping per-thread stacks "
            "(send SIGINFO/SIGUSR1 for additional dumps)",
            stalled_for,
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
