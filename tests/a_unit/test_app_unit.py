"""CLI entry-point tests for ``terminux.app``."""

from __future__ import annotations

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
