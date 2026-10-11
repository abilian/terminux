"""Tests for the app entrypoint: headless + windowed wiring (faked GUI)."""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest

import terminux.__main__  # noqa: F401  (import executes module body for coverage)
from terminux import app
from terminux.server.asgi import build_app


def test_free_port_returns_bindable_port() -> None:
    p = app._free_port()
    assert isinstance(p, int)
    assert 1024 <= p <= 65535


class _FakeServer:
    def __init__(self, *_a, **_k) -> None:
        self.started = True
        self.should_exit = False

    def run(self) -> None:
        return


def _patch_common(monkeypatch) -> None:
    monkeypatch.setattr(app.uvicorn, "Server", _FakeServer)
    monkeypatch.setattr(app.uvicorn, "Config", lambda *a, **k: None)
    # Real controller, but no disk persistence.
    monkeypatch.setattr(app, "build_app", lambda persist=True: build_app(persist=False))


class _SlowStartServer(_FakeServer):
    """Starts after a short delay, like real uvicorn: ``run`` blocks until
    ``started`` flips, so the wait loop sees a live thread while polling."""

    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self.started = False

    def run(self) -> None:
        time.sleep(0.06)
        self.started = True


def test_main_no_window(monkeypatch) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["terminux", "--no-window", "--port", "9"])
    app.main()  # returns once the (fake) server thread finishes


def test_main_no_window_waits_for_server_start(monkeypatch) -> None:
    monkeypatch.setattr(app.uvicorn, "Server", _SlowStartServer)
    monkeypatch.setattr(app.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(app, "build_app", lambda persist=True: build_app(persist=False))
    monkeypatch.setattr(sys, "argv", ["terminux", "--no-window"])
    app.main()  # exercises the `while not server.started: sleep` loop body


def test_main_windowed_with_fake_webview(monkeypatch) -> None:
    monkeypatch.setattr(app.uvicorn, "Server", _FakeServer)
    monkeypatch.setattr(app.uvicorn, "Config", lambda *a, **k: None)
    holder: dict[str, object] = {}

    def _build(persist: bool = True) -> object:
        built = build_app(persist=False)
        holder["app"] = built
        return built

    monkeypatch.setattr(app, "build_app", _build)

    recorded: dict[str, object] = {}
    create_kw: dict[str, object] = {}

    class FakeEvent:
        def __init__(self) -> None:
            self._handlers: list = []

        def __iadd__(self, fn):
            self._handlers.append(fn)
            return self

        def fire(self, *args) -> None:
            for fn in self._handlers:
                fn(*args)

    class FakeElement:
        def on(self, event: str, handler) -> None:
            recorded[event] = handler.callback

    class FakeDom:
        document = FakeElement()

    class FakeWindow:
        def __init__(self) -> None:
            self.events = types.SimpleNamespace(
                loaded=FakeEvent(),
                closed=FakeEvent(),
                resized=FakeEvent(),
                moved=FakeEvent(),
            )
            self.dom = FakeDom()

    win = FakeWindow()

    fake_webview = types.ModuleType("webview")

    def _create(*_a, **k):
        create_kw.update(k)
        return win

    fake_webview.create_window = _create  # type: ignore[attr-defined]
    fake_webview.active_window = lambda: win  # type: ignore[attr-defined]

    def fake_start(**_k) -> None:
        # **_k absorbs the ``menu=`` kwarg the real start() now receives.
        win.events.loaded.fire()  # -> _register_drop registers a drop handler
        drop = recorded["drop"]
        drop({"dataTransfer": {"files": [{"pywebviewFullPath": "/tmp/x.pdf"}]}})
        drop({})  # no dataTransfer
        drop("not-a-dict")  # event not a dict
        drop({"dataTransfer": {"files": [{"name": "n"}, "weird"]}})  # no full path
        win.events.resized.fire(1280, 800)  # geometry tracked in ui
        win.events.moved.fire(30, 40)
        win.events.closed.fire()  # -> _shutdown

    fake_webview.start = fake_start  # type: ignore[attr-defined]

    fake_dom = types.ModuleType("webview.dom")

    class DOMEventHandler:
        def __init__(self, callback, prevent_default: bool = False, **_k) -> None:
            self.callback = callback

    fake_dom.DOMEventHandler = DOMEventHandler  # type: ignore[attr-defined]

    # The native menu construction in _build_menu pulls in webview.menu;
    # stub it minimally so the test doesn't need pywebview installed.
    fake_menu = types.ModuleType("webview.menu")

    class _StubMenu:
        def __init__(self, label, items=None) -> None:
            self.label = label
            self.items = items or []

    class _StubMenuAction:
        def __init__(self, label, callback) -> None:
            self.label = label
            self.callback = callback

    class _StubSeparator:
        pass

    fake_menu.Menu = _StubMenu  # type: ignore[attr-defined]
    fake_menu.MenuAction = _StubMenuAction  # type: ignore[attr-defined]
    fake_menu.MenuSeparator = _StubSeparator  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setitem(sys.modules, "webview.dom", fake_dom)
    monkeypatch.setitem(sys.modules, "webview.menu", fake_menu)

    monkeypatch.setattr(sys, "argv", ["terminux"])
    app.main()

    # Window opened at the persisted geometry (defaults here)...
    assert create_kw["width"] == 1100
    assert create_kw["height"] == 720
    assert create_kw["x"] is None
    # ...and resize/move updated the in-memory UiPrefs.
    ctl = holder["app"].state.controller  # type: ignore[attr-defined]
    assert (ctl.state.ui.win_w, ctl.state.ui.win_h) == (1280, 800)
    assert (ctl.state.ui.win_x, ctl.state.ui.win_y) == (30, 40)


def test_main_windowed_create_window_none(monkeypatch) -> None:
    _patch_common(monkeypatch)
    fake_webview = types.ModuleType("webview")
    fake_webview.create_window = lambda *a, **k: None  # type: ignore[attr-defined]
    fake_webview.start = lambda **_k: None  # type: ignore[attr-defined]
    fake_dom = types.ModuleType("webview.dom")
    fake_dom.DOMEventHandler = lambda *a, **k: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setitem(sys.modules, "webview.dom", fake_dom)
    monkeypatch.setattr(sys, "argv", ["terminux"])
    try:
        app.main()
    except RuntimeError as e:
        assert "failed to create application window" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def _free_tcp_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _assert_page_token_works(url: str, port: int) -> None:
    """The page loads, and the token it hands the browser is the one the
    API accepts."""
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        page = resp.read().decode()
    page_token = re.search(r'TERMINUX_TOKEN = "([^"]+)"', page)
    assert page_token, page
    api_url = f"http://127.0.0.1:{port}/api/state?t={page_token.group(1)}"
    with urllib.request.urlopen(api_url, timeout=5) as resp:
        assert resp.status == 200


@pytest.mark.skipif(sys.platform == "win32", reason="--daemon needs fork()")
def test_daemon_prints_the_url_goes_to_the_background_and_logs(tmp_path) -> None:
    """``terminux --daemon`` returns once the server answers, printing the
    URL with the public host; the server keeps running detached, logs to a
    file and records its PID. A second daemon is refused while the first
    runs; ``--stop`` ends it and removes the PID file."""

    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    port = _free_tcp_port()
    argv = [sys.executable, "-m", "terminux", "--daemon", "--port", str(port)]
    started = subprocess.run(
        [*argv, "--public-host", "devbox.example.com"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    url = re.search(r"http://devbox\.example\.com:\d+/\?t=\S+", started.stderr)
    pid = re.search(r"pid (\d+)", started.stderr)
    log_file = re.search(r"log: (.+)", started.stderr)
    pid_file = re.search(r"pid file: (.+)", started.stderr)
    assert url and pid and log_file and pid_file, started.stderr
    pid_path = Path(pid_file.group(1))
    try:
        assert pid_path.read_text(encoding="utf-8").strip() == pid.group(1)
        _assert_page_token_works(
            url.group(0).replace("devbox.example.com", "127.0.0.1"), port
        )
        assert "server ready" in Path(log_file.group(1)).read_text(encoding="utf-8")

        again = subprocess.run(
            argv, env=env, capture_output=True, text=True, timeout=30, check=False
        )
        assert again.returncode == 1
        assert f"already running (pid {pid.group(1)})" in again.stderr
    finally:
        stopped = subprocess.run(
            [sys.executable, "-m", "terminux", "--stop"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if stopped.returncode:  # don't leak the daemon if --stop is broken
            os.kill(int(pid.group(1)), signal.SIGTERM)
    assert stopped.returncode == 0, stopped.stderr
    assert f"stopped (pid {pid.group(1)})" in stopped.stderr
    assert not pid_path.exists()
    nothing = subprocess.run(
        [sys.executable, "-m", "terminux", "--stop"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert nothing.returncode == 1
    assert "no terminux daemon is running" in nothing.stderr
