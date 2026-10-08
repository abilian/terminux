"""CLI entry-point tests for ``terminux.app``."""

from __future__ import annotations

import logging
import re
import sys
import threading

import pytest

from terminux import app as app_mod


def test_wait_until_started_exits_when_server_thread_dies() -> None:
    """A dead server thread (port in use) must raise, not spin forever."""

    class _DeadServer:
        started = False

    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    with pytest.raises(SystemExit, match="failed to start"):
        app_mod._wait_until_started(_DeadServer(), thread, "127.0.0.1:1")


def test_connect_mode_does_not_arm_watchdog(monkeypatch) -> None:
    """--connect runs no local server, so the loop watchdog must stay off.

    Regression: the watchdog monitors the local server's asyncio heartbeat;
    armed in client mode it warned every 10 s about a loop that doesn't exist.
    """
    calls: list[str] = []
    monkeypatch.setattr(app_mod, "start_watchdog", lambda: calls.append("watchdog"))
    monkeypatch.setattr(app_mod, "_install_freeze_diagnostics", lambda: None)
    monkeypatch.setattr(
        app_mod,
        "_run_connected",
        lambda url, **_k: calls.append(f"connect:{url}"),
    )
    monkeypatch.setattr(
        "sys.argv", ["terminux", "--connect", "http://localhost:8443/?t=abc-def-ghi"]
    )
    app_mod.main()
    assert calls == ["connect:http://localhost:8443/?t=abc-def-ghi"]


# ----- App Nap -----------------------------------------------------------


@pytest.mark.skipif(sys.platform != "darwin", reason="App Nap is macOS-only")
def test_app_nap_opt_out_returns_a_live_activity_token() -> None:
    """Drives the real NSProcessInfo API: a wrong constant or selector name
    raises here. The token is what keeps the opt-out alive."""
    from Foundation import NSProcessInfo

    token = app_mod._disable_macos_app_nap()
    assert token is not None
    NSProcessInfo.processInfo().endActivity_(token)


def test_app_nap_opt_out_is_a_no_op_off_macos(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.sys, "platform", "linux")
    assert app_mod._disable_macos_app_nap() is None


# ----- log format ----------------------------------------------------------


def _line_from_configured_logging(*, debug: bool) -> str:
    """Run _configure_logging on a bare root logger and format one record
    with the handler it installs, restoring everything afterwards.

    Done inside the test body: pytest attaches its capture handler to the
    root logger at the start of each test phase, and basicConfig is a
    no-op whenever the root logger already has a handler.
    """
    root = logging.getLogger()
    terminux_logger = logging.getLogger("terminux")
    access = logging.getLogger("uvicorn.access")
    saved = (root.handlers[:], root.level, terminux_logger.level, access.filters[:])
    root.handlers.clear()
    try:
        app_mod._configure_logging(debug=debug, trace=False)
        (handler,) = root.handlers
        record = logging.LogRecord(
            "terminux.x", logging.WARNING, __file__, 1, "hello", None, None
        )
        line = handler.format(record)
        handler.close()
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        terminux_logger.setLevel(saved[2])
        access.filters[:] = saved[3]
    return line


def test_default_log_lines_carry_a_full_timestamp() -> None:
    """Without timestamps a long-running log can't be matched to events
    (display sleep, a disk filling up): every mode stamps a full date."""
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} WARNING terminux\.x: hello",
        _line_from_configured_logging(debug=False),
    )


def test_debug_log_lines_add_milliseconds() -> None:
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} WARNING terminux\.x: hello",
        _line_from_configured_logging(debug=True),
    )
