"""Unit tests for the AppState domain model."""

from __future__ import annotations

from terminux.core.model import (
    AppState,
    Tab,
    UiPrefs,
    Workspace,
    WorkspaceStatus,
)


def test_default_has_one_workspace_one_tab() -> None:
    s = AppState.default()
    assert len(s.workspaces) == 1
    ws = s.workspaces[0]
    assert s.active_workspace_id == ws.id
    assert len(ws.tab_ids) == 1
    assert ws.active_tab_id == ws.tab_ids[0]


def test_workspace_name_autoincrements_skipping_used() -> None:
    s = AppState()
    a = s.add_workspace()
    b = s.add_workspace()
    assert a.name == "workspace 1"
    assert b.name == "workspace 2"
    c = s.add_workspace(name="workspace 4")
    d = s.add_workspace()  # 1,2 used, 4 used -> 3
    assert c.name == "workspace 4"
    assert d.name == "workspace 3"


def test_user_set_name_round_trips() -> None:
    s = AppState.default()
    ws = s.workspaces[0]
    ws.name = "pinned"
    ws.user_set_name = True
    restored = AppState.from_json(s.to_json())
    rw = restored.workspaces[0]
    assert rw.name == "pinned"
    assert rw.user_set_name is True


def test_get_workspace_missing_returns_none() -> None:
    assert AppState().get_workspace("nope") is None


def test_remove_workspace_returns_tab_ids_and_reassigns_active() -> None:
    s = AppState.default()
    first = s.workspaces[0]
    second = s.add_workspace()
    tab = s.add_tab(second.id)
    assert tab is not None
    s.set_active_workspace(second.id)
    removed = s.remove_workspace(second.id)
    assert removed == [tab.id]  # its tab ids are reported for terminal cleanup
    assert second.id not in [w.id for w in s.workspaces]
    assert s.active_workspace_id == first.id


def test_remove_workspace_unknown_returns_empty() -> None:
    assert AppState.default().remove_workspace("ghost") == []


def test_remove_workspace_drops_its_tabs() -> None:
    s = AppState.default()
    ws = s.workspaces[0]
    tab_ids = list(ws.tab_ids)
    out = s.remove_workspace(ws.id)
    assert out == tab_ids
    assert s.tabs == {}
    assert s.active_workspace_id is None


def test_set_active_workspace_invalid_noop() -> None:
    s = AppState.default()
    before = s.active_workspace_id
    s.set_active_workspace("missing")
    assert s.active_workspace_id == before


def test_set_active_clears_unseen_after_dwell() -> None:
    """Visiting a workspace clears its unseen flags only if the user
    dwelled at least ``VISIT_DWELL_SECONDS``. Brief fly-bys leave the
    flags intact so a quick ``Cmd+1 / Cmd+2 / Cmd+3`` sweep across a
    row of green dots doesn't silently dismiss them."""
    from terminux.core.model import VISIT_DWELL_SECONDS

    s = AppState.default()
    ws = s.workspaces[0]
    other = s.add_workspace()
    s.add_tab(other.id)
    # Park the user elsewhere so we can deactivate `ws` cleanly.
    s.set_active_workspace(other.id)

    ws.has_unseen_output = True
    s.tabs[ws.active_tab_id].has_unseen_output = True

    # Fly-by: visit ws then leave immediately. Flags must survive.
    s.set_active_workspace(ws.id)
    s.set_active_workspace(other.id)
    assert ws.has_unseen_output is True
    assert s.tabs[ws.active_tab_id].has_unseen_output is True

    # Real visit: dwell at least VISIT_DWELL_SECONDS, then leave.
    s.set_active_workspace(ws.id)
    assert ws.active_since_at is not None
    ws.active_since_at -= VISIT_DWELL_SECONDS + 0.1  # fake the wait
    s.set_active_workspace(other.id)
    assert ws.has_unseen_output is False
    assert s.tabs[ws.active_tab_id].has_unseen_output is False


def test_reactivating_same_workspace_is_noop() -> None:
    """A no-op re-activation must not reset the dwell timer — a stray
    duplicate ``set_active_workspace`` call would otherwise restart the
    clock and turn a long visit into a fly-by."""
    s = AppState.default()
    ws = s.workspaces[0]
    started_at = ws.active_since_at
    assert started_at is not None
    s.set_active_workspace(ws.id)
    assert ws.active_since_at == started_at


def test_add_tab_unknown_workspace_returns_none() -> None:
    assert AppState().add_tab("nope") is None


def test_remove_tab_reassigns_active_then_none() -> None:
    s = AppState.default()
    ws = s.workspaces[0]
    t1 = ws.tab_ids[0]
    t2 = s.add_tab(ws.id)
    assert ws.active_tab_id == t2.id
    s.remove_tab(t2.id)
    assert ws.active_tab_id == t1
    s.remove_tab(t1)
    assert ws.active_tab_id is None
    assert ws.tab_ids == []


def test_remove_non_active_workspace_keeps_active() -> None:
    s = AppState.default()
    active = s.workspaces[0]
    other = s.add_workspace()
    s.add_tab(other.id)
    # `active` stays selected; removing `other` exercises the non-active branch.
    s.remove_workspace(other.id)
    assert s.active_workspace_id == active.id


def test_dwell_clears_only_active_tab() -> None:
    """When a dwell is long enough to clear flags on deactivation, only
    the active tab's flags are cleared — other tabs in the workspace
    keep theirs (the user only "saw" the one tab they were on)."""
    from terminux.core.model import VISIT_DWELL_SECONDS

    s = AppState.default()
    ws = s.workspaces[0]
    other = s.add_workspace()
    s.add_tab(other.id)
    s.set_active_workspace(other.id)  # park elsewhere

    first_tab = ws.active_tab_id
    second = s.add_tab(ws.id)  # second becomes ws.active_tab_id
    assert second is not None
    s.tabs[first_tab].has_unseen_output = True
    s.tabs[second.id].has_unseen_output = True

    s.set_active_workspace(ws.id)
    ws.active_since_at -= VISIT_DWELL_SECONDS + 0.1
    s.set_active_workspace(other.id)
    assert s.tabs[second.id].has_unseen_output is False
    assert s.tabs[first_tab].has_unseen_output is True


def test_workspace_status_missing_is_idle() -> None:
    assert AppState().workspace_status("x") == WorkspaceStatus.IDLE


def test_workspace_status_active() -> None:
    s = AppState.default()
    assert s.workspace_status(s.workspaces[0].id) == WorkspaceStatus.ACTIVE


def test_workspace_status_exited_unseen_idle() -> None:
    s = AppState.default()
    other = s.add_workspace()
    s.add_tab(other.id)
    s.set_active_workspace(s.workspaces[0].id)  # `other` not active
    # No live terminal on `other` -> EXITED
    assert s.workspace_status(other.id) == WorkspaceStatus.EXITED
    # Mark a live terminal -> not exited; unseen -> RUNNING
    s.tabs[other.tab_ids[0]].terminal_id = "term-1"
    other.has_unseen_output = True
    assert s.workspace_status(other.id) == WorkspaceStatus.UNSEEN
    other.has_unseen_output = False
    assert s.workspace_status(other.id) == WorkspaceStatus.IDLE


def test_to_from_json_roundtrip() -> None:
    s = AppState.default()
    ws = s.workspaces[0]
    ws.name = "demo"
    s.tabs[ws.active_tab_id].title = "build"
    s.ui.font_size = 18
    restored = AppState.from_json(s.to_json())
    assert restored.workspaces[0].name == "demo"
    assert restored.tabs[restored.workspaces[0].tab_ids[0]].title == "build"
    assert restored.ui.font_size == 18
    assert restored.active_workspace_id == restored.workspaces[0].id


def test_tab_cwd_round_trips_into_spawn_and_last_cwd() -> None:
    tab = Tab(title="t", last_cwd="/work/proj")
    restored = Tab.from_json(tab.to_json())
    assert restored.last_cwd == "/work/proj"
    assert restored.spawn_cwd == "/work/proj"


def test_from_json_defaults_for_missing_fields() -> None:
    tab = Tab.from_json({"id": "t1"})
    assert tab.title == "shell"
    assert tab.user_set_title is False
    assert tab.spawn_cwd is None
    assert tab.last_cwd is None
    ws = Workspace.from_json({"id": "w1"})
    assert ws.name == "workspace"
    assert ws.active_tab_id is None
    ui = UiPrefs.from_json({})
    assert ui.sidebar_width == 220
    assert ui.win_w == 1100
    assert ui.win_x is None
    assert ui.win_maximized is False
    assert ui.copy_on_select is False


def test_uiprefs_window_round_trip() -> None:
    ui = UiPrefs.from_json(
        {
            "sidebar_width": 300,
            "win_w": 1280,
            "win_h": 800,
            "win_x": 42,
            "win_y": 7,
            "copy_on_select": True,
        },
    )
    again = UiPrefs.from_json(ui.to_json())
    assert again.sidebar_width == 300
    assert (again.win_w, again.win_h) == (1280, 800)
    assert (again.win_x, again.win_y) == (42, 7)
    assert again.copy_on_select is True


def test_repair_drops_dangling_and_guarantees_baseline() -> None:
    raw = {
        "workspaces": [
            {
                "id": "w1",
                "name": "a",
                "tab_ids": ["t1", "ghost"],
                "active_tab_id": "ghost",
            },
            {"id": "w2", "name": "b", "tab_ids": [], "active_tab_id": None},
        ],
        "tabs": [{"id": "t1", "title": "x"}, {"id": "orphan", "title": "y"}],
        "active_workspace_id": "does-not-exist",
    }
    s = AppState.from_json(raw)
    w1 = s.get_workspace("w1")
    assert w1 is not None
    assert w1.tab_ids == ["t1"]
    assert w1.active_tab_id == "t1"  # dangling active fixed
    w2 = s.get_workspace("w2")
    assert w2 is not None
    assert len(w2.tab_ids) == 1  # empty workspace got a fresh tab
    assert "orphan" not in s.tabs  # orphan tab dropped
    assert s.active_workspace_id == "w1"  # bad active fixed to first


def test_repair_no_workspaces_creates_default() -> None:
    s = AppState.from_json({"workspaces": [], "tabs": []})
    assert len(s.workspaces) == 1
    assert len(s.workspaces[0].tab_ids) == 1


def test_view_json_exposes_status_and_live() -> None:
    s = AppState.default()
    ws = s.workspaces[0]
    s.tabs[ws.active_tab_id].terminal_id = "tid"
    view = s.view_json()
    assert view["workspaces"][0]["status"] == "active"
    assert view["tabs"][ws.active_tab_id]["live"] is True
    assert view["active_workspace_id"] == ws.id
