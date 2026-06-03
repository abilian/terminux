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
