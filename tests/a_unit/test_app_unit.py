"""CLI entry-point tests for ``terminux.app``."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

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


def test_windows_gets_an_ico_window_icon() -> None:
    """WinForms builds the window icon with System.Drawing.Icon, which
    rejects a PNG and crashes the UI thread (first launch on Windows)."""
    ico = app_mod._ASSETS_DIR / "icon.ico"
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"  # ICO magic
    expected = "icon.ico" if sys.platform == "win32" else "icon.png"
    assert app_mod.WINDOW_ICON.name == expected
    assert app_mod.WINDOW_ICON.exists()


@pytest.mark.parametrize(
    ("platform", "has_edit"), [("win32", True), ("linux", True), ("darwin", False)]
)
def test_edit_menu_only_where_the_webview_has_none(
    monkeypatch, platform, has_edit
) -> None:
    """pywebview adds a native Edit menu on macOS only; elsewhere terminux
    provides Copy / Paste / Select All itself (there's no context menu)."""
    monkeypatch.setattr(app_mod.sys, "platform", platform)
    menus = app_mod._build_menu(SimpleNamespace(active_window=lambda: None))
    titles = [m.title for m in menus]
    assert ("Edit" in titles) is has_edit
    if has_edit:
        edit = menus[titles.index("Edit")]
        labels = [getattr(i, "title", None) for i in edit.items]
        assert labels == ["Copy", "Paste", None, "Select All"]


def test_windows_edit_paste_hands_the_clipboard_text_to_the_page(monkeypatch) -> None:
    """WebView2 refuses the page's clipboard API, so on Windows the menu's
    Paste reads the clipboard in Python and passes the text (JSON-quoted)."""
    monkeypatch.setattr(app_mod.sys, "platform", "win32")
    monkeypatch.setattr(app_mod.clipboard, "read_text", lambda: 'echo "hi"\n')
    calls: list[str] = []
    window = SimpleNamespace(evaluate_js=calls.append)
    menus = app_mod._build_menu(SimpleNamespace(active_window=lambda: window))
    edit = next(m for m in menus if m.title == "Edit")
    paste = next(i for i in edit.items if getattr(i, "title", None) == "Paste")
    paste.function()
    assert calls == ['window.terminux?.pasteText("echo \\"hi\\"\\n")']


@pytest.mark.parametrize(
    ("public_host", "bind", "expected_host"),
    [
        ("devbox.example.com", "0.0.0.0", "devbox.example.com"),  # noqa: S104
        (None, "127.0.0.1", "127.0.0.1"),
        ("fe80::1", "::", "[fe80::1]"),
    ],
)
def test_connect_url_names_a_routable_host(public_host, bind, expected_host) -> None:
    url = app_mod._connect_url(public_host, bind, 8443, "abc-def-ghi")
    assert url == f"http://{expected_host}:8443/?t=abc-def-ghi"


def test_connect_url_names_this_machine_for_a_wildcard_bind(monkeypatch) -> None:
    monkeypatch.setattr(app_mod.socket, "getfqdn", lambda: "box.lan")
    assert app_mod._connect_url(None, "0.0.0.0", 1, "t").startswith("http://box.lan:1/")  # noqa: S104


def test_banner_warns_when_the_server_is_loopback_only() -> None:
    assert "SSH tunnel" in app_mod._banner("http://h:1/?t=x", "127.0.0.1")
    assert "SSH tunnel" not in app_mod._banner("http://h:1/?t=x", "0.0.0.0")  # noqa: S104


def test_pid_file_counts_only_a_live_process(tmp_path) -> None:
    pid_path = tmp_path / "terminux.pid"
    assert app_mod._running_daemon_pid(pid_path) is None  # no file
    pid_path.write_text("garbage\n", encoding="utf-8")
    assert app_mod._running_daemon_pid(pid_path) is None
    dead = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    pid_path.write_text(dead, encoding="utf-8")  # left behind by a crash
    assert app_mod._running_daemon_pid(pid_path) is None
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    assert app_mod._running_daemon_pid(pid_path) == os.getpid()


@pytest.mark.skipif(sys.platform == "win32", reason="no SIGTERM delivery on Windows")
def test_sigterm_closes_the_window_while_the_gui_loop_holds_the_main_thread() -> None:
    """``terminux --stop`` on a windowed daemon closes the window, which
    saves the state, even though the GUI loop never returns to Python."""
    closed = threading.Event()
    win = SimpleNamespace(destroy=closed.set)
    previous = signal.getsignal(signal.SIGTERM)
    try:
        app_mod._close_on_sigterm(win)  # type: ignore[arg-type]
        os.kill(os.getpid(), signal.SIGTERM)
        assert closed.wait(timeout=5)
    finally:
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGTERM, previous)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_full_screen_is_in_our_view_menu_on_macos(monkeypatch, platform) -> None:
    """pywebview's View menu, which only had "Enter Full Screen", is turned
    off on macOS so there's a single View menu; ours takes over the item."""
    monkeypatch.setattr(app_mod.sys, "platform", platform)
    toggled: list[bool] = []
    window = SimpleNamespace(toggle_fullscreen=lambda: toggled.append(True))
    menus = app_mod._build_menu(SimpleNamespace(active_window=lambda: window))
    assert [m.title for m in menus].count("View") == 1
    view = next(m for m in menus if m.title == "View")
    items = {getattr(i, "title", None): i for i in view.items}
    assert ("Toggle Full Screen" in items) is (platform == "darwin")
    if platform == "darwin":
        items["Toggle Full Screen"].function()
        assert toggled == [True]


def test_ctrl_shift_v_pastes_natively_and_other_keys_pass_through() -> None:
    """macOS: the patched ``keyDown_`` pastes on Ctrl+Shift+V (any layout:
    the physical V key) and hands every other key to the original."""
    shift, ctrl, option = 1 << 17, 1 << 18, 1 << 19
    key_v, key_c = 9, 8

    class Host:
        def __init__(self) -> None:
            self.events: list[str] = []

        def keyDown_(self, event: object) -> None:
            self.events.append("forwarded")

        def paste_(self, _sender: object) -> None:
            self.events.append("pasted")

    class Event:
        def __init__(self, flags: int, code: int) -> None:
            self._flags, self._code = flags, code

        def modifierFlags(self) -> int:
            return self._flags | 0x100  # device-dependent low bits are ignored

        def keyCode(self) -> int:
            return self._code

    cocoa = ModuleType("cocoa")
    cocoa.BrowserView = SimpleNamespace(WebKitHost=Host)  # type: ignore[attr-defined]
    app_mod._paste_on_ctrl_shift_v(cocoa)
    host = Host()
    for flags, code in (
        (ctrl | shift, key_v),
        (ctrl, key_v),
        (ctrl | shift | option, key_v),
        (ctrl | shift, key_c),
    ):
        host.keyDown_(Event(flags, code))
    assert host.events == ["pasted", "forwarded", "forwarded", "forwarded"]
