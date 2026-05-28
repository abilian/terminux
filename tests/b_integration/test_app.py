"""Tests for the app entrypoint: headless + windowed wiring (faked GUI)."""

from __future__ import annotations

import sys
import types

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
    """`started` flips to True only after the first poll (covers the wait)."""

    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self._polls = 0

    @property  # type: ignore[override]
    def started(self) -> bool:
        self._polls += 1
        return self._polls > 1

    @started.setter
    def started(self, _v: bool) -> None:
        pass


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
    fake_webview.start = lambda: None  # type: ignore[attr-defined]
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
