"""Unit tests for the freeze diagnostics: heartbeat, watchdog, timer."""

from __future__ import annotations

import contextlib
import logging
import threading
import time

from terminux import diagnostics


class _WatchdogStopError(Exception):
    """Sentinel used to break out of the watchdog loop in tests."""


def test_beat_advances_last_beat() -> None:
    before = diagnostics._WatchdogState.last_beat
    time.sleep(0.005)
    diagnostics.beat()
    assert diagnostics._WatchdogState.last_beat > before


def test_start_watchdog_is_idempotent(monkeypatch) -> None:
    """``start_watchdog`` may be called many times; only one thread spawns."""
    spawned: list[threading.Thread] = []
    real_thread = threading.Thread

    def fake_thread(*a, **k):
        t = real_thread(*a, **k)
        spawned.append(t)
        return t

    # Reset so the call actually tries to spawn under the lock.
    monkeypatch.setattr(diagnostics._WatchdogState, "started", False)
    monkeypatch.setattr(diagnostics.threading, "Thread", fake_thread)
    diagnostics.start_watchdog()
    diagnostics.start_watchdog()
    diagnostics.start_watchdog()
    assert len(spawned) == 1


def test_time_op_logs_slow(caplog) -> None:
    """An op that exceeds ``SLOW_OP_THRESHOLD`` lands at WARNING."""
    with (
        caplog.at_level(logging.WARNING, logger=diagnostics.log.name),
        diagnostics.time_op("slow-thing"),
    ):
        time.sleep(diagnostics.SLOW_OP_THRESHOLD + 0.01)
    assert any(
        "slow slow-thing" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )


def test_time_op_silent_when_fast(caplog) -> None:
    """Fast ops don't log unless DEBUG is enabled."""
    with (
        caplog.at_level(logging.WARNING, logger=diagnostics.log.name),
        diagnostics.time_op("fast-thing"),
    ):
        pass  # microseconds
    assert not any("fast-thing" in r.message for r in caplog.records)


def test_time_op_logs_at_debug_when_enabled(caplog) -> None:
    """With DEBUG enabled, every op (slow or not) is logged."""
    with (
        caplog.at_level(logging.DEBUG, logger=diagnostics.log.name),
        diagnostics.time_op("traced-thing"),
    ):
        pass
    assert any(
        "traced-thing" in r.message and r.levelno == logging.DEBUG
        for r in caplog.records
    )


def test_watchdog_warns_on_stall(monkeypatch, caplog) -> None:
    """If the heartbeat doesn't advance, the watchdog logs a warning.

    Drives ``_run_watchdog`` directly with a tiny stall threshold and a
    stub for ``time.sleep`` so we don't actually wait — and we break out
    after the first iteration via an exception.
    """
    monkeypatch.setattr(diagnostics, "STALL_THRESHOLD", 0.001)
    monkeypatch.setattr(diagnostics, "WARN_INTERVAL", 0.0)
    # Make ``last_beat`` ancient so the watchdog sees a stall on first poll.
    monkeypatch.setattr(
        diagnostics._WatchdogState, "last_beat", time.monotonic() - 10.0
    )

    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 2:  # let one iteration of the loop run, then bail
            raise _WatchdogStopError

    monkeypatch.setattr(diagnostics.time, "sleep", fake_sleep)

    with (
        caplog.at_level(logging.WARNING, logger=diagnostics.log.name),
        contextlib.suppress(_WatchdogStopError),
    ):
        diagnostics._run_watchdog()

    assert any(
        "event loop unresponsive" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )


# ----- stall vs. suspension ---------------------------------------------
# ``_Monitor.observe`` is pure over explicit clock values, so these drive
# it with numbers instead of sleeping. Thresholds are the real defaults:
# STALL_THRESHOLD = 3 s, WARN_INTERVAL = 10 s, POLL_INTERVAL = 1 s.

Finding = diagnostics.Finding


def test_monitor_quiet_when_the_loop_beats() -> None:
    m = diagnostics._Monitor()
    assert m.observe(slept_at=100.0, now=101.0, last_beat=100.8) is None


def test_monitor_reports_a_stall_while_the_process_runs() -> None:
    """On-time wake-ups but a stale heartbeat: the loop is stuck."""
    m = diagnostics._Monitor()
    assert m.observe(slept_at=100.0, now=101.0, last_beat=95.0) == (
        Finding.STALLED,
        6.0,
    )


def test_monitor_rate_limits_repeat_stall_reports() -> None:
    m = diagnostics._Monitor()
    assert m.observe(slept_at=100.0, now=101.0, last_beat=95.0) is not None
    # Same stall 5 s later: inside WARN_INTERVAL, stays quiet.
    assert m.observe(slept_at=105.0, now=106.0, last_beat=95.0) is None
    # 10 s after the first report it speaks again.
    assert m.observe(slept_at=110.0, now=111.0, last_beat=95.0) == (
        Finding.STALLED,
        16.0,
    )


def test_monitor_blames_the_process_not_the_loop_when_it_overslept() -> None:
    """A 1 s sleep that took 301 s means every thread was frozen (App Nap,
    swapping): one SUSPENDED finding, never a stall dump — even though the
    heartbeat is 302 s stale."""
    m = diagnostics._Monitor()
    assert m.observe(slept_at=100.0, now=401.0, last_beat=99.0) == (
        Finding.SUSPENDED,
        300.0,
    )


def test_monitor_gives_a_resumed_loop_a_fresh_threshold() -> None:
    m = diagnostics._Monitor()
    m.observe(slept_at=100.0, now=401.0, last_beat=99.0)  # suspended
    # 1 s after resuming, the loop hasn't beaten yet: not its fault.
    assert m.observe(slept_at=401.0, now=402.0, last_beat=99.0) is None
    # Still silent 4 s after resuming while the process runs: a real stall,
    # measured from the resume, not from before the suspension.
    assert m.observe(slept_at=404.0, now=405.0, last_beat=99.0) == (
        Finding.STALLED,
        4.0,
    )


def test_monitor_turns_the_field_log_pattern_into_suspensions() -> None:
    """The 2026-10 field log: watchdog wake-ups 67 s and 334 s apart while
    the loop was idle. Before, each was a 110-line stack dump; now each is
    a suspension and nothing is blamed on the loop."""
    m = diagnostics._Monitor()
    findings = [
        m.observe(slept_at=0.0, now=67.5, last_beat=0.0),
        m.observe(slept_at=67.5, now=401.5, last_beat=0.0),
        m.observe(slept_at=401.5, now=402.5, last_beat=401.9),  # loop beat
    ]
    assert [f[0] if f else None for f in findings] == [
        Finding.SUSPENDED,
        Finding.SUSPENDED,
        None,
    ]


def test_watchdog_logs_a_suspension_as_one_line(monkeypatch, caplog) -> None:
    """End to end through ``_run_watchdog``: an oversleep logs one INFO line
    and no stack dump."""
    # slept_at, a 300 s-late wake-up, then the next slept_at before the
    # second sleep ends the loop.
    clock = iter([100.0, 401.0, 401.0])
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: next(clock))
    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise _WatchdogStopError

    monkeypatch.setattr(diagnostics.time, "sleep", fake_sleep)
    dumps: list[object] = []
    monkeypatch.setattr(
        diagnostics.faulthandler, "dump_traceback", lambda **k: dumps.append(k)
    )
    monkeypatch.setattr(diagnostics._WatchdogState, "last_beat", 99.0)

    with (
        caplog.at_level(logging.INFO, logger=diagnostics.log.name),
        contextlib.suppress(_WatchdogStopError),
    ):
        diagnostics._run_watchdog()

    messages = [r.getMessage() for r in caplog.records]
    assert any("process got no CPU for 300.0s" in m for m in messages)
    assert not any("event loop unresponsive" in m for m in messages)
    assert dumps == []
