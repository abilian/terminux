"""Domain controller: owns ``AppState`` and the live ``Terminal`` registry.

Pure Python — no Starlette types. The HTTP/WebSocket handlers in
``terminux.server.api`` are a thin shell that calls into this and shapes
the result into responses; the controller knows nothing about HTTP.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from terminux.core.model import AppState, Workspace
from terminux.core.persistence import (
    delete_scrollback,
    load_scrollback,
    load_state,
    save_scrollback,
    save_state,
)
from terminux.core.shellprobe import default_cwd, default_shell
from terminux.core.terminal import Terminal, TerminalRegistry

# Active-time tracker config: a workspace accrues seconds only while the
# user has typed into one of its tabs within this window. Captures real
# focus, ignores "left for lunch" and long-running commands the user
# isn't watching.
ACTIVITY_IDLE_THRESHOLD = 30.0  # seconds since last keystroke

# Window during which PTY output is treated as visit-cleanup, not real
# news. The moment a workspace is deactivated, the TUI's redraw tail and
# xterm's own settling effects (cursor restore, mode restoration, etc.)
# emit a stream of bytes that would otherwise flag the workspace as
# ``has_unseen_output=True`` — leaving a misleading green "ready for
# attention" dot the moment the user looks away.
UNSEEN_GRACE_SECONDS = 5.0

# Minimum sustained busy time before a busy→idle transition counts as
# a "task finished" ready signal. Filters out cosmetic blips and very
# short commands; Claude Code returning to its prompt after a real
# thinking session, ``sleep 10`` finishing without shell integration,
# and ``make test`` ending all cross this comfortably.
READY_TRANSITION_SECONDS = 5.0


def _shell_quote(path: str) -> str:
    """POSIX single-quote escaping so paths with spaces/specials are safe."""
    return "'" + path.replace("'", "'\\''") + "'"


class AppController:
    """Owns AppState + live terminals. All access is on the server event loop."""

    def __init__(self, *, persist: bool = True) -> None:
        self._persist = persist
        self.state: AppState = load_state() if persist else AppState.default()
        self.terminals = TerminalRegistry()
        self.spawn_lock = asyncio.Lock()  # serialize PTY creation (§8)
        # Starlette runs sync route handlers in anyio's threadpool, so multiple
        # of them can mutate `state` (and its `tabs` dict) concurrently. This
        # reentrant lock serializes every state access; route handlers acquire
        # it around the synchronous mutation block (never across `await`).
        self.lock = threading.RLock()
        # Per-workspace cumulative active seconds for this terminus session.
        # Transient (in-memory only) — resets when the process exits or when
        # the user explicitly invokes "Reset session activity counters".
        self._active_seconds: dict[str, float] = {}
        self._last_input_at: float | None = None
        # Wall-clock time when the activity session started, used to drive
        # the "session started Xm ago" header in the stats overlay.
        self._session_started_at: float = time.time()
        # Per-terminal busy-transition tracker. Used by the 1 Hz ticker to
        # detect busy→idle transitions that lasted long enough to count
        # as a "task finished" signal (drives the green "ready" dot).
        self._was_busy: dict[str, bool] = {}
        self._busy_since: dict[str, float] = {}

    def save(self) -> None:
        if not self._persist:
            return
        with self.lock:
            self._snapshot_cwds()
            save_state(self.state)

    def save_scrollback(self, tab_id: str, content: str) -> None:
        if not self._persist or not self.state.ui.scrollback_persist:
            return
        save_scrollback(tab_id, content)

    def load_scrollback(self, tab_id: str) -> str | None:
        if not self._persist or not self.state.ui.scrollback_persist:
            return None
        return load_scrollback(tab_id)

    def delete_scrollback(self, tab_id: str) -> None:
        # Always best-effort delete (even with persist=False, in case the
        # pref was toggled mid-run and a stale file lingers).
        if self._persist:
            delete_scrollback(tab_id)

    def note_input(self) -> None:
        """Called when keystrokes arrive over a PTY WebSocket — the only
        signal we treat as "user is actually working here right now"."""
        self._last_input_at = time.monotonic()

    def tick(self, dt: float, *, now: float | None = None) -> None:
        """Credit the active workspace with ``dt`` seconds iff the user has
        typed something in the last ``ACTIVITY_IDLE_THRESHOLD`` seconds.

        Called by the 1 Hz background ticker; ``now`` is injectable for
        deterministic testing.
        """
        if self._last_input_at is None:
            return
        current = now if now is not None else time.monotonic()
        if current - self._last_input_at > ACTIVITY_IDLE_THRESHOLD:
            return
        with self.lock:
            ws_id = self.state.active_workspace_id
            if ws_id is None or self.state.get_workspace(ws_id) is None:
                return
            self._active_seconds[ws_id] = self._active_seconds.get(ws_id, 0.0) + dt

    def active_seconds(self, ws_id: str) -> int:
        return int(self._active_seconds.get(ws_id, 0.0))

    def reset_activity(self) -> None:
        """Clear all per-workspace counters and start a fresh session."""
        self._active_seconds.clear()
        self._last_input_at = None
        self._session_started_at = time.time()

    @property
    def session_started_at(self) -> float:
        """Epoch seconds when the current activity session started."""
        return self._session_started_at

    def _snapshot_cwds(self) -> None:
        """Capture each live shell's cwd so a restart can respawn there.

        Iterates a list snapshot — callers may already hold ``self.lock`` (so
        the dict can't change underfoot), but ``list()`` makes the intent
        local to this method and survives anyone calling it without the lock.
        """
        for tab in list(self.state.tabs.values()):
            if tab.terminal_id is None:
                continue
            term = self.terminals.get(tab.terminal_id)
            if term is not None:
                live = term.cwd()
                if live:
                    tab.last_cwd = live

    def ensure_terminal(self, tab_id: str, cols: int, rows: int) -> Terminal | None:
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return None
            if tab.terminal_id is not None:
                existing = self.terminals.get(tab.terminal_id)
                if existing is not None and not existing.exited:
                    return existing
            cwd = tab.spawn_cwd or default_cwd()
            if not Path(cwd).is_dir():  # e.g. a restored dir since deleted
                cwd = default_cwd()
            term = self.terminals.create(default_shell(), cwd, cols, rows)
            tab.terminal_id = term.id
            term.on_activity = lambda: self._mark_activity(tab_id)
            term.on_attention = lambda: self._mark_ready(tab_id)
            term.on_exit = lambda _code: setattr(tab, "terminal_id", None)
            return term

    def inherit_cwd(self, ws_id: str) -> str | None:
        """Working directory of a workspace's currently active live shell."""
        with self.lock:
            ws = self.state.get_workspace(ws_id)
            if ws is None or ws.active_tab_id is None:
                return None
            tab = self.state.tabs.get(ws.active_tab_id)
            if tab is None or tab.terminal_id is None:
                return None
            term = self.terminals.get(tab.terminal_id)
            return term.cwd() if term is not None else None

    def active_terminal(self) -> Terminal | None:
        with self.lock:
            ws_id = self.state.active_workspace_id
            ws = self.state.get_workspace(ws_id) if ws_id else None
            if ws is None or ws.active_tab_id is None:
                return None
            tab = self.state.tabs.get(ws.active_tab_id)
            if tab is None or tab.terminal_id is None:
                return None
            return self.terminals.get(tab.terminal_id)

    def _workspace_label(self, ws: Workspace) -> str:
        """Display name: a pinned rename, else the **first** tab's directory.

        Tracks ``ws.tab_ids[0]`` rather than the active tab so jumping
        between tabs within a workspace doesn't keep renaming it; the
        drag-reorderable tab list gives the user a direct way to
        promote a different tab into the naming slot.

        Resolves to a directory immediately (never the numbered name): a
        live shell's cwd, else the last-seen cwd, else where it will spawn,
        else the default cwd. lsof is only run for the active workspace (or
        once per tab) to keep the per-poll cost bounded.
        """
        if ws.user_set_name:
            return ws.name
        cwd: str | None = None
        if ws.tab_ids:
            first_tid = ws.tab_ids[0]
            tab = self.state.tabs.get(first_tid)
            if tab is not None:
                if tab.terminal_id is not None:
                    term = self.terminals.get(tab.terminal_id)
                    is_active = ws.id == self.state.active_workspace_id
                    if term is not None and (is_active or tab.last_cwd is None):
                        live = term.cwd()
                        if live:
                            tab.last_cwd = live
                cwd = tab.last_cwd or tab.spawn_cwd
        if cwd is None:
            cwd = default_cwd()
        path = Path(cwd)
        if path == Path.home():
            return "~"
        return path.name or ws.name

    def state_view(self) -> dict[str, Any]:
        """`AppState.view_json` with cwd-derived workspace display names and
        a ``"busy"`` status promotion when a workspace has a foreground task
        running and nothing more urgent to signal (priority: active > exited
        > busy > unseen > idle). Computed on demand at view time so we never
        pay the ``tcgetpgrp`` syscall outside the ~2 Hz frontend poll.

        ``busy`` beats ``unseen`` because a chatty long-running task (Claude
        Code's spinner, a build's progress lines, ``tail -f``) would
        otherwise keep flipping the workspace green while it's still
        working. "Output happened" is only a useful "go check this" signal
        once the task has finished; until then "still running" is the
        more accurate cue.
        """
        with self.lock:
            view = self.state.view_json()
            view["session_started_at"] = self.session_started_at
            now = time.monotonic()
            by_id = {w.id: w for w in self.state.workspaces}
            for wv in view["workspaces"]:
                ws = by_id.get(wv["id"])
                if ws is None:
                    continue
                wv["name"] = self._workspace_label(ws)
                wv["active_seconds"] = self.active_seconds(ws.id)
                # Active/exited carry more urgent meaning and stay untouched.
                # Idle and unseen are both demoted to busy when any tab has
                # a foreground task running — UNLESS the workspace was just
                # deactivated: the visit-redraw tail / xterm settling would
                # otherwise paint the dot orange for the few seconds after
                # the user looked away.
                in_grace = ws.last_active_at is not None and (
                    now - ws.last_active_at < UNSEEN_GRACE_SECONDS
                )
                if (
                    wv["status"] in {"idle", "unseen"}
                    and not in_grace
                    and any(
                        (tab := self.state.tabs.get(tid)) is not None
                        and tab.terminal_id is not None
                        and (term := self.terminals.get(tab.terminal_id)) is not None
                        and term.is_busy()
                        for tid in ws.tab_ids
                    )
                ):
                    wv["status"] = "busy"
            return view

    def paste_paths(self, paths: list[str]) -> None:
        """Insert dropped file paths (shell-quoted) into the active terminal.

        Called from the pywebview thread; ``Terminal.write`` is a plain
        ``os.write`` to the PTY master, which is safe across threads.
        """
        term = self.active_terminal()
        if term is None or not paths:
            return
        text = " ".join(_shell_quote(p) for p in paths) + " "
        term.write(text.encode())

    def _mark_activity(self, tab_id: str) -> None:
        """Per-tab "output happened in a non-viewed tab" — drives the
        small activity indicator in the tab bar. Workspace-level "ready"
        is a separate signal handled by ``_mark_ready`` / the busy→idle
        tracker — generic output no longer flips the workspace dot."""
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return
            now = time.monotonic()
            for ws in self.state.workspaces:
                if tab_id not in ws.tab_ids:
                    continue
                is_active = (
                    ws.id == self.state.active_workspace_id
                    and ws.active_tab_id == tab_id
                )
                if is_active:
                    continue
                # Grace period: output within UNSEEN_GRACE_SECONDS of the
                # workspace being deactivated is treated as visit-cleanup
                # (redraw tail, xterm settling) and does not flag unseen.
                if ws.last_active_at is not None and (
                    now - ws.last_active_at < UNSEEN_GRACE_SECONDS
                ):
                    continue
                tab.has_unseen_output = True

    def _mark_ready(self, tab_id: str) -> None:
        """Fire the workspace-level "ready for review" signal. Called
        when one of the strict task-finished sources triggers: raw
        ``BEL`` outside any OSC, ``OSC 9`` notification, ``OSC 133;D``
        (≥ 2 s), or the kernel-level busy→idle transition (≥ 5 s,
        driven by ``poll_busy_transitions``).

        Skipped while the workspace is currently active or sitting in
        the post-visit grace window."""
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return
            now = time.monotonic()
            for ws in self.state.workspaces:
                if tab_id not in ws.tab_ids:
                    continue
                if ws.id == self.state.active_workspace_id:
                    continue
                if ws.last_active_at is not None and (
                    now - ws.last_active_at < UNSEEN_GRACE_SECONDS
                ):
                    continue
                ws.has_unseen_output = True

    def poll_busy_transitions(self) -> None:
        """1 Hz heartbeat: detect kernel-level busy→idle transitions. A
        terminal that was sustained-busy for at least
        ``READY_TRANSITION_SECONDS`` then went quiet is treated as
        "task finished" and feeds the workspace's "ready" signal — the
        same end-state as ``OSC 133;D`` but for shells/apps that don't
        speak shell-integration (Claude Code returning to its prompt,
        ``sleep 10`` ending, ``make test`` finishing without OSC 133)."""
        with self.lock:
            now = time.monotonic()
            for ws in self.state.workspaces:
                for tid in ws.tab_ids:
                    tab = self.state.tabs.get(tid)
                    if tab is None or tab.terminal_id is None:
                        continue
                    term = self.terminals.get(tab.terminal_id)
                    if term is None:
                        continue
                    term_id = term.id
                    is_busy_now = term.is_busy()
                    was_busy = self._was_busy.get(term_id, False)
                    if is_busy_now and not was_busy:
                        self._busy_since[term_id] = now
                    elif was_busy and not is_busy_now:
                        since = self._busy_since.pop(term_id, None)
                        if (
                            since is not None
                            and (now - since) >= READY_TRANSITION_SECONDS
                        ):
                            self._mark_ready(tid)
                    self._was_busy[term_id] = is_busy_now
