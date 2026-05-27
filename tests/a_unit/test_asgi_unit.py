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


def test_unseen_grace_period_after_deactivation() -> None:
    """Output that arrives within UNSEEN_GRACE_SECONDS of a workspace
    being deactivated does not flip the unseen flag — that window
    catches the visit-cleanup tail (xterm settling, TUI redraw
    trailing bytes) rather than real user-facing news."""
    import time

    from terminux.server import asgi

    ctl = AppController(persist=False)
    a = ctl.state.workspaces[0]
    b = ctl.state.add_workspace()
    b_tab = ctl.state.add_tab(b.id)
    assert b_tab is not None

    # Visit b then go back to a; b.last_active_at is now ~ monotonic().
    ctl.state.set_active_workspace(b.id)
    ctl.state.set_active_workspace(a.id)
    assert b.last_active_at is not None

    # Inside the grace window: output is suppressed.
    ctl._mark_activity(b_tab.id)
    assert b.has_unseen_output is False
    assert ctl.state.tabs[b_tab.id].has_unseen_output is False

    # Outside the grace window: the same output flags unseen normally.
    b.last_active_at = time.monotonic() - asgi.UNSEEN_GRACE_SECONDS - 0.1
    ctl._mark_activity(b_tab.id)
    assert b.has_unseen_output is True
    assert ctl.state.tabs[b_tab.id].has_unseen_output is True


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


def test_busy_status_wins_over_unseen() -> None:
    """A workspace whose foreground task is still running shows ``busy``
    even when it has unseen output — otherwise a chatty long-running
    task (Claude Code's spinner, a noisy build) flips the dot to
    ``unseen`` (green) while it's still working."""

    class FakeTerm:
        def is_busy(self) -> bool:
            return True

        def cwd(self) -> str | None:  # called by _workspace_label
            return None

    ctl = AppController(persist=False)
    # Add a second workspace so the first isn't the active one (active
    # status would otherwise outrank everything).
    other = ctl.state.add_workspace()
    ctl.state.add_tab(other.id)
    ctl.state.set_active_workspace(other.id)

    target = ctl.state.workspaces[0]
    tab = ctl.state.tabs[target.tab_ids[0]]
    tab.terminal_id = "fake-term"
    target.has_unseen_output = True  # would normally make it status=unseen
    # Push target past the post-visit grace window so busy promotion is
    # eligible (the new grace fix would otherwise hold it at "unseen").
    target.last_active_at = None
    ctl.terminals._terminals["fake-term"] = FakeTerm()  # type: ignore[assignment]

    view = ctl.state_view()
    target_view = next(w for w in view["workspaces"] if w["id"] == target.id)
    assert target_view["status"] == "busy"

    # Sanity: once the task finishes (is_busy → False), unseen wins.
    class IdleTerm:
        def is_busy(self) -> bool:
            return False

        def cwd(self) -> str | None:
            return None

    ctl.terminals._terminals["fake-term"] = IdleTerm()  # type: ignore[assignment]
    view = ctl.state_view()
    target_view = next(w for w in view["workspaces"] if w["id"] == target.id)
    assert target_view["status"] == "unseen"


def test_busy_promotion_suppressed_inside_grace() -> None:
    """During the post-visit grace window, even a genuinely busy terminal
    in a just-deactivated workspace doesn't flip the dot orange. The
    visit-redraw tail dominates the recent-bytes window and would
    otherwise paint the dot busy the moment the user looks away."""
    import time

    from terminux.server import asgi

    class FakeTerm:
        def is_busy(self) -> bool:
            return True

        def cwd(self) -> str | None:
            return None

    ctl = AppController(persist=False)
    target = ctl.state.workspaces[0]
    other = ctl.state.add_workspace()
    ctl.state.add_tab(other.id)
    # Visit target then leave it — stamps target.last_active_at ≈ now.
    ctl.state.set_active_workspace(target.id)
    ctl.state.set_active_workspace(other.id)
    assert target.last_active_at is not None

    tab = ctl.state.tabs[target.tab_ids[0]]
    tab.terminal_id = "fake-term"
    ctl.terminals._terminals["fake-term"] = FakeTerm()  # type: ignore[assignment]

    # Inside the grace window: busy promotion is suppressed.
    view = ctl.state_view()
    target_view = next(w for w in view["workspaces"] if w["id"] == target.id)
    assert target_view["status"] == "idle"

    # Outside the grace window: the same FakeTerm promotes to busy.
    target.last_active_at = time.monotonic() - asgi.UNSEEN_GRACE_SECONDS - 0.1
    view = ctl.state_view()
    target_view = next(w for w in view["workspaces"] if w["id"] == target.id)
    assert target_view["status"] == "busy"


def test_workspace_label_tracks_first_tab_not_active(tmp_path) -> None:
    """The workspace label follows ``tab_ids[0]``, not ``active_tab_id`` —
    switching tabs within a workspace must not keep renaming it."""
    ctl = AppController(persist=False)
    ws = ctl.state.workspaces[0]
    first = ctl.state.tabs[ws.tab_ids[0]]
    second = ctl.state.add_tab(ws.id, spawn_cwd="/var/log")
    assert second is not None
    first.spawn_cwd = str(tmp_path)
    # Activate the second tab; the first is still in slot 0.
    ws.active_tab_id = second.id
    assert ws.tab_ids[0] == first.id
    assert ctl._workspace_label(ws) == tmp_path.name


def test_user_set_name_persists_through_save_load(tmp_path, monkeypatch) -> None:
    """Renaming a workspace and round-tripping through the on-disk JSON
    keeps both ``name`` and ``user_set_name`` — the auto-tracker stays
    pinned across a restart."""
    from terminux.core import persistence

    state_file = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "state_path", lambda: state_file)

    ctl = AppController(persist=True)
    ws = ctl.state.workspaces[0]
    ws.name = "Project Alpha"
    ws.user_set_name = True
    ctl.save()

    reloaded = AppController(persist=True)
    rws = reloaded.state.workspaces[0]
    assert rws.name == "Project Alpha"
    assert rws.user_set_name is True
    # And the display label honours the pin even if the first tab's cwd
    # would otherwise resolve to something else.
    rtab = reloaded.state.tabs[rws.tab_ids[0]]
    rtab.spawn_cwd = "/var/log"
    assert reloaded._workspace_label(rws) == "Project Alpha"


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


# ----- activity tracker ---------------------------------------------


def test_activity_tracker_credits_active_workspace_only_while_recent() -> None:
    """Ticks credit the active workspace iff the user has typed in the
    last ACTIVITY_IDLE_THRESHOLD seconds; otherwise nothing accrues."""
    ctl = AppController(persist=False)
    ws_id = ctl.state.workspaces[0].id

    # No input yet → never accrues, even with an active workspace.
    ctl.tick(1.0, now=100.0)
    assert ctl.active_seconds(ws_id) == 0

    # User just typed at t=100; ticks at t=100, 105 both credit (< 30 s).
    ctl._last_input_at = 100.0
    ctl.tick(1.0, now=100.0)
    ctl.tick(1.0, now=105.0)
    assert ctl.active_seconds(ws_id) == 2

    # Ticks past the 30 s idle threshold stop crediting.
    ctl.tick(1.0, now=200.0)
    assert ctl.active_seconds(ws_id) == 2


def test_activity_tracker_follows_active_workspace_change() -> None:
    """Switching workspaces credits the new one going forward; the old
    one keeps its accumulated seconds (no double-counting)."""
    ctl = AppController(persist=False)
    ws_a = ctl.state.workspaces[0].id
    ws_b = ctl.state.add_workspace(name="b").id

    ctl._last_input_at = 100.0
    ctl.state.set_active_workspace(ws_a)
    ctl.tick(1.0, now=100.0)
    ctl.tick(1.0, now=101.0)
    ctl.state.set_active_workspace(ws_b)
    ctl.tick(1.0, now=102.0)
    ctl.tick(1.0, now=103.0)

    assert ctl.active_seconds(ws_a) == 2
    assert ctl.active_seconds(ws_b) == 2


def test_reset_activity_clears_counters_and_advances_session_start() -> None:
    """The palette's "Reset session activity counters" wipes per-workspace
    accruals AND resets ``session_started_at`` so the stats overlay's "X
    ago" header restarts at 0."""
    ctl = AppController(persist=False)
    ws_id = ctl.state.workspaces[0].id
    ctl._last_input_at = 100.0
    ctl.tick(5.0, now=100.0)
    assert ctl.active_seconds(ws_id) == 5

    before = ctl.session_started_at
    ctl.reset_activity()
    assert ctl.active_seconds(ws_id) == 0
    assert ctl._last_input_at is None
    assert ctl.session_started_at >= before  # never goes backwards


def test_note_input_sets_last_input() -> None:
    """note_input refreshes the idle window — keystrokes resume crediting
    after a long idle period."""
    ctl = AppController(persist=False)
    ws_id = ctl.state.workspaces[0].id

    ctl._last_input_at = 100.0
    ctl.tick(1.0, now=200.0)  # 100 s idle → no credit
    assert ctl.active_seconds(ws_id) == 0

    ctl.note_input()
    # note_input uses time.monotonic() so re-check the post-condition via
    # a tick at the same instant.
    ctl.tick(1.0, now=ctl._last_input_at)
    assert ctl.active_seconds(ws_id) == 1
