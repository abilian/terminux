"""In-memory authoritative app state: workspaces and tabs.

Only structure (ids, names, order, active selection, UI prefs) is persisted.
Live terminals are transient and rebuilt on demand; see ``core.terminal``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex


class WorkspaceStatus(str, Enum):
    """Auto-derived sidebar status (functional spec §4.4)."""

    ACTIVE = "active"
    RUNNING = "running"
    IDLE = "idle"
    EXITED = "exited"


@dataclass
class Tab:
    """One terminal session inside a workspace."""

    id: str = field(default_factory=_new_id)
    title: str = "shell"
    user_set_title: bool = False
    # Transient (never persisted):
    terminal_id: str | None = None
    has_unseen_output: bool = False
    needs_attention: bool = False  # BEL / OSC 9 from a non-viewed tab
    spawn_cwd: str | None = None  # directory inherited from the previous tab
    last_cwd: str | None = None  # last observed shell cwd (for the label)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "user_set_title": self.user_set_title,
            "cwd": self.last_cwd,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Tab:
        cwd = data.get("cwd")
        cwd = str(cwd) if cwd is not None else None
        return cls(
            id=str(data["id"]),
            title=str(data.get("title", "shell")),
            user_set_title=bool(data.get("user_set_title")),
            # Restore the shell where it was at exit; last_cwd also lets the
            # workspace label show that directory before the shell respawns.
            spawn_cwd=cwd,
            last_cwd=cwd,
        )


@dataclass
class Workspace:
    """A named container for a set of terminal tabs."""

    id: str = field(default_factory=_new_id)
    name: str = "workspace"
    # When False the display name tracks the active shell's cwd; an explicit
    # rename sets this True and pins `name`.
    user_set_name: bool = False
    tab_ids: list[str] = field(default_factory=list)
    active_tab_id: str | None = None
    # Transient: set when a tab produces output while this workspace is not active.
    has_unseen_output: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "user_set_name": self.user_set_name,
            "tab_ids": list(self.tab_ids),
            "active_tab_id": self.active_tab_id,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Workspace:
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "workspace")),
            user_set_name=bool(data.get("user_set_name")),
            tab_ids=[str(t) for t in data.get("tab_ids", [])],
            active_tab_id=(
                str(data["active_tab_id"])
                if data.get("active_tab_id") is not None
                else None
            ),
        )


@dataclass
class UiPrefs:
    """Persisted UI preferences."""

    sidebar_width: int = 220
    sidebar_collapsed: bool = False
    font_size: int = 13
    # iTerm2-style: copy the selection to the clipboard as soon as it's made.
    copy_on_select: bool = False
    # Window geometry; None position means "let the OS place it".
    win_w: int = 1100
    win_h: int = 720
    win_x: int | None = None
    win_y: int | None = None
    win_maximized: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "sidebar_width": self.sidebar_width,
            "sidebar_collapsed": self.sidebar_collapsed,
            "font_size": self.font_size,
            "copy_on_select": self.copy_on_select,
            "win_w": self.win_w,
            "win_h": self.win_h,
            "win_x": self.win_x,
            "win_y": self.win_y,
            "win_maximized": self.win_maximized,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> UiPrefs:
        def _opt_int(key: str) -> int | None:
            v = data.get(key)
            return int(v) if v is not None else None

        return cls(
            sidebar_width=int(data.get("sidebar_width", 220)),
            sidebar_collapsed=bool(data.get("sidebar_collapsed")),
            font_size=int(data.get("font_size", 13)),
            copy_on_select=bool(data.get("copy_on_select")),
            win_w=int(data.get("win_w", 1100)),
            win_h=int(data.get("win_h", 720)),
            win_x=_opt_int("win_x"),
            win_y=_opt_int("win_y"),
            win_maximized=bool(data.get("win_maximized")),
        )


SCHEMA_VERSION = 1


@dataclass
class AppState:
    """Authoritative state. All mutation happens on the backend event loop."""

    workspaces: list[Workspace] = field(default_factory=list)
    tabs: dict[str, Tab] = field(default_factory=dict)
    active_workspace_id: str | None = None
    ui: UiPrefs = field(default_factory=UiPrefs)

    # ----- construction -------------------------------------------------

    @classmethod
    def default(cls) -> AppState:
        """A single workspace with one tab — the always-valid baseline."""
        state = cls()
        ws = state.add_workspace(name="workspace 1")
        state.add_tab(ws.id)
        state.active_workspace_id = ws.id
        return state

    # ----- workspace ops ------------------------------------------------

    def add_workspace(self, name: str | None = None) -> Workspace:
        ws = Workspace(name=name or self._next_workspace_name())
        self.workspaces.append(ws)
        return ws

    def _next_workspace_name(self) -> str:
        used = {w.name for w in self.workspaces}
        i = 1
        while f"workspace {i}" in used:
            i += 1
        return f"workspace {i}"

    def get_workspace(self, ws_id: str) -> Workspace | None:
        return next((w for w in self.workspaces if w.id == ws_id), None)

    def remove_workspace(self, ws_id: str) -> list[str]:
        """Remove a workspace; return the ids of its tabs (caller kills terminals)."""
        ws = self.get_workspace(ws_id)
        if ws is None:
            return []
        tab_ids = list(ws.tab_ids)
        for tid in tab_ids:
            self.tabs.pop(tid, None)
        self.workspaces = [w for w in self.workspaces if w.id != ws_id]
        if self.active_workspace_id == ws_id:
            self.active_workspace_id = (
                self.workspaces[0].id if self.workspaces else None
            )
        return tab_ids

    def set_active_workspace(self, ws_id: str) -> None:
        if self.get_workspace(ws_id) is None:
            return
        self.active_workspace_id = ws_id
        ws = self.get_workspace(ws_id)
        if ws is not None:
            ws.has_unseen_output = False
            for tid in ws.tab_ids:
                tab = self.tabs.get(tid)
                if tab is not None and tid == ws.active_tab_id:
                    tab.has_unseen_output = False
                    tab.needs_attention = False

    # ----- tab ops ------------------------------------------------------

    def add_tab(
        self,
        ws_id: str,
        title: str = "shell",
        spawn_cwd: str | None = None,
    ) -> Tab | None:
        ws = self.get_workspace(ws_id)
        if ws is None:
            return None
        tab = Tab(title=title, spawn_cwd=spawn_cwd)
        self.tabs[tab.id] = tab
        ws.tab_ids.append(tab.id)
        ws.active_tab_id = tab.id
        return tab

    def remove_tab(self, tab_id: str) -> None:
        for ws in self.workspaces:
            if tab_id in ws.tab_ids:
                ws.tab_ids.remove(tab_id)
                if ws.active_tab_id == tab_id:
                    ws.active_tab_id = ws.tab_ids[-1] if ws.tab_ids else None
        self.tabs.pop(tab_id, None)

    # ----- status -------------------------------------------------------

    def workspace_status(self, ws_id: str) -> WorkspaceStatus:
        ws = self.get_workspace(ws_id)
        if ws is None:
            return WorkspaceStatus.IDLE
        if ws_id == self.active_workspace_id:
            return WorkspaceStatus.ACTIVE
        has_live = any(
            (t := self.tabs.get(tid)) is not None and t.terminal_id is not None
            for tid in ws.tab_ids
        )
        if not has_live and ws.tab_ids:
            return WorkspaceStatus.EXITED
        if ws.has_unseen_output:
            return WorkspaceStatus.RUNNING
        return WorkspaceStatus.IDLE

    # ----- serialization ------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "workspaces": [w.to_json() for w in self.workspaces],
            "tabs": [t.to_json() for t in self.tabs.values()],
            "active_workspace_id": self.active_workspace_id,
            "ui": self.ui.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AppState:
        tabs = {}
        for raw in data.get("tabs", []):
            tab = Tab.from_json(raw)
            tabs[tab.id] = tab
        workspaces = [Workspace.from_json(w) for w in data.get("workspaces", [])]
        state = cls(
            workspaces=workspaces,
            tabs=tabs,
            active_workspace_id=data.get("active_workspace_id"),
            ui=UiPrefs.from_json(data.get("ui", {})),
        )
        state._repair()
        return state

    def _repair(self) -> AppState:
        """Drop dangling references; guarantee >= 1 workspace with >= 1 tab."""
        for ws in self.workspaces:
            ws.tab_ids = [tid for tid in ws.tab_ids if tid in self.tabs]
            if ws.active_tab_id not in ws.tab_ids:
                ws.active_tab_id = ws.tab_ids[-1] if ws.tab_ids else None
            if not ws.tab_ids:
                tab = Tab()
                self.tabs[tab.id] = tab
                ws.tab_ids.append(tab.id)
                ws.active_tab_id = tab.id
        # drop orphan tabs not referenced by any workspace
        referenced = {tid for ws in self.workspaces for tid in ws.tab_ids}
        self.tabs = {tid: t for tid, t in self.tabs.items() if tid in referenced}
        if not self.workspaces:
            ws = self.add_workspace(name="workspace 1")
            self.add_tab(ws.id)
        if self.get_workspace(self.active_workspace_id or "") is None:
            self.active_workspace_id = self.workspaces[0].id
        return self

    def view_json(self) -> dict[str, Any]:
        """Snapshot for the frontend, including derived status."""
        return {
            "workspaces": [
                {
                    **w.to_json(),
                    "status": self.workspace_status(w.id).value,
                    "attention": any(
                        (tb := self.tabs.get(t)) is not None and tb.needs_attention
                        for t in w.tab_ids
                    ),
                }
                for w in self.workspaces
            ],
            "tabs": {
                tid: {
                    **t.to_json(),
                    "live": t.terminal_id is not None,
                    "has_unseen_output": t.has_unseen_output,
                    "needs_attention": t.needs_attention,
                }
                for tid, t in self.tabs.items()
            },
            "active_workspace_id": self.active_workspace_id,
            "ui": self.ui.to_json(),
        }
