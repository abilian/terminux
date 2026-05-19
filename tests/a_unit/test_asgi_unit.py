"""Unit tests for asgi helpers and controller branches without a real PTY."""

from __future__ import annotations

from terminux.core.model import AppState
from terminux.server import asgi
from terminux.server.asgi import AppController, _shell_quote


def test_shell_quote_plain() -> None:
    assert _shell_quote("/tmp/file.pdf") == "'/tmp/file.pdf'"


def test_shell_quote_with_space() -> None:
    assert _shell_quote("/a b/c") == "'/a b/c'"


def test_shell_quote_escapes_single_quote() -> None:
    assert _shell_quote("a'b") == "'a'\\''b'"


def test_active_terminal_none_when_no_active_workspace() -> None:
    ctl = AppController(persist=False)
    ctl.state.active_workspace_id = None
    assert ctl.active_terminal() is None


def test_active_terminal_none_when_tab_has_no_terminal() -> None:
    ctl = AppController(persist=False)
    # Default workspace/tab exists but no terminal spawned.
    assert ctl.active_terminal() is None


def test_active_terminal_none_when_active_tab_missing() -> None:
    ctl = AppController(persist=False)
    ws = ctl.state.workspaces[0]
    ws.active_tab_id = None
    assert ctl.active_terminal() is None


def test_active_terminal_none_when_terminal_id_dangling() -> None:
    ctl = AppController(persist=False)
    ws = ctl.state.workspaces[0]
    ctl.state.tabs[ws.active_tab_id].terminal_id = "ghost"
    assert ctl.active_terminal() is None


def test_paste_paths_noop_without_terminal() -> None:
    ctl = AppController(persist=False)
    ctl.paste_paths(["/x"])  # must not raise
    ctl.paste_paths([])


def test_inherit_cwd_none_branches() -> None:
    ctl = AppController(persist=False)
    assert ctl.inherit_cwd("missing-ws") is None
    ws = ctl.state.workspaces[0]
    assert ctl.inherit_cwd(ws.id) is None  # tab has no terminal
    ws.active_tab_id = None
    assert ctl.inherit_cwd(ws.id) is None


def test_ensure_terminal_unknown_tab_returns_none() -> None:
    ctl = AppController(persist=False)
    assert ctl.ensure_terminal("no-such-tab", 80, 24) is None


def test_mark_activity_branches() -> None:
    ctl = AppController(persist=False)
    ctl._mark_activity("ghost")  # unknown tab -> early return

    active_ws = ctl.state.workspaces[0]
    other = ctl.state.add_workspace()
    bg_tab = ctl.state.add_tab(other.id)
    assert bg_tab is not None
    ctl.state.set_active_workspace(active_ws.id)

    # Output on a tab in a non-active workspace marks both as unseen.
    ctl._mark_activity(bg_tab.id)
    assert ctl.state.tabs[bg_tab.id].has_unseen_output is True
    assert other.has_unseen_output is True

    # Output on the active tab of the active workspace marks nothing.
    active_tab = active_ws.active_tab_id
    ctl._mark_activity(active_tab)
    assert ctl.state.tabs[active_tab].has_unseen_output is False


def test_mark_attention_and_clear_on_view() -> None:
    ctl = AppController(persist=False)
    ctl._mark_attention("ghost")  # unknown tab -> early return

    active_ws = ctl.state.workspaces[0]
    other = ctl.state.add_workspace()
    bg_tab = ctl.state.add_tab(other.id)
    assert bg_tab is not None
    ctl.state.set_active_workspace(active_ws.id)

    # Attention on a non-viewed tab flags the tab; workspace view derives it.
    ctl._mark_attention(bg_tab.id)
    assert ctl.state.tabs[bg_tab.id].needs_attention is True
    v = ctl.state_view()
    assert v["tabs"][bg_tab.id]["needs_attention"] is True
    other_view = next(w for w in v["workspaces"] if w["id"] == other.id)
    assert other_view["attention"] is True

    # Viewing the tab clears it (switch workspace to `other`).
    ctl.state.set_active_workspace(other.id)
    assert ctl.state.tabs[bg_tab.id].needs_attention is False

    # Attention on the currently-viewed tab is ignored.
    ctl._mark_attention(bg_tab.id)
    assert ctl.state.tabs[bg_tab.id].needs_attention is False


def test_persist_true_loads_and_saves(monkeypatch) -> None:
    saved: list[AppState] = []
    monkeypatch.setattr(asgi, "load_state", AppState.default)
    monkeypatch.setattr(asgi, "save_state", lambda s: saved.append(s))
    ctl = AppController(persist=True)
    ctl.save()
    assert saved and saved[0] is ctl.state


def test_save_snapshots_live_cwd_so_it_persists(monkeypatch) -> None:
    monkeypatch.setattr(asgi, "load_state", AppState.default)
    monkeypatch.setattr(asgi, "save_state", lambda _s: None)
    ctl = AppController(persist=True)
    tab = ctl.state.tabs[ctl.state.workspaces[0].active_tab_id]
    tab.terminal_id = "term-1"

    class FakeTerm:
        def cwd(self) -> str:
            return "/work/proj"

    ctl.terminals._terminals["term-1"] = FakeTerm()  # type: ignore[assignment]
    ctl.save()
    assert tab.last_cwd == "/work/proj"
    # And that cwd survives a serialize/reload as the next spawn dir.
    restored = AppState.from_json(ctl.state.to_json())
    rtab = restored.tabs[restored.workspaces[0].active_tab_id]
    assert rtab.spawn_cwd == "/work/proj"


def test_workspace_label_tracks_cwd_and_pin(tmp_path) -> None:
    from pathlib import Path

    ctl = AppController(persist=False)
    ws = ctl.state.workspaces[0]
    tab = ctl.state.tabs[ws.active_tab_id]

    # No shell yet -> the directory it will spawn in (default cwd == home
    # in the test env), never the numbered name.
    assert ctl._workspace_label(ws) == "~"

    # spawn_cwd (set before a shell exists) drives the label.
    tab.spawn_cwd = str(tmp_path)
    assert ctl._workspace_label(ws) == tmp_path.name

    # A remembered cwd wins over spawn_cwd (workspace switched away).
    tab.last_cwd = "/var/log"
    assert ctl._workspace_label(ws) == "log"

    # Home directory shows as "~".
    tab.last_cwd = str(Path.home())
    assert ctl._workspace_label(ws) == "~"

    # A pinned (user-set) name wins regardless of cwd.
    ws.name = "pinned"
    ws.user_set_name = True
    assert ctl._workspace_label(ws) == "pinned"


def test_state_view_overrides_names() -> None:
    ctl = AppController(persist=False)
    ws = ctl.state.workspaces[0]
    ctl.state.tabs[ws.active_tab_id].spawn_cwd = "/var/log"
    view = ctl.state_view()
    assert view["workspaces"][0]["name"] == "log"


def test_spawn_lock_is_an_asyncio_lock() -> None:
    import asyncio

    ctl = AppController(persist=False)
    assert isinstance(ctl.spawn_lock, asyncio.Lock)


def test_pump_out_emits_dropped_then_exit(monkeypatch) -> None:
    import asyncio
    import types

    from terminux.core import terminal as term_mod
    from terminux.core.terminal import Subscriber
    from terminux.server.asgi import _pump_out

    monkeypatch.setattr(term_mod, "OUTBOUND_CAP", 4)
    monkeypatch.setattr(term_mod, "FLUSH_INTERVAL", 0)

    class FakeWS:
        def __init__(self) -> None:
            self.json: list = []
            self.bytes: list = []

        async def send_json(self, obj) -> None:
            self.json.append(obj)

        async def send_bytes(self, b) -> None:
            self.bytes.append(b)

    async def go() -> None:
        sub = Subscriber()
        sub.feed(b"123456789")  # > cap -> dropped, keeps tail b"6789"
        sub.close()
        ws = FakeWS()
        term = types.SimpleNamespace(exit_code=0)
        await asyncio.wait_for(_pump_out(ws, sub, term), timeout=2)
        assert ws.json == [{"type": "dropped"}, {"type": "exit", "code": 0}]
        assert b"".join(ws.bytes) == b"6789"

    asyncio.run(go())
