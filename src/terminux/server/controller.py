"""Domain controller: owns ``AppState`` and the live ``Terminal`` registry.

Pure Python — no Starlette types. The HTTP/WebSocket handlers in
``terminux.server.api`` are a thin shell that calls into this and shapes
the result into responses; the controller knows nothing about HTTP.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from terminux.core.model import AppState, Workspace, WorkspaceStatus
from terminux.core.persistence import (
    delete_scrollback,
    load_scrollback,
    load_state,
    save_scrollback,
    save_state_json,
)
from terminux.core.pty_backend import PtyBackend, spawn_pty
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


def _shell_quote(path: str, shell: str = "sh") -> str:
    """Quote ``path`` for ``shell`` so spaces and specials are safe.

    POSIX single quotes by default; on Windows, PowerShell single quotes
    (``'`` doubled) or cmd double quotes (``"`` can't occur in a path).
    """
    name = PureWindowsPath(shell).stem.lower()
    if name == "cmd":
        return '"' + path + '"'
    if name in {"pwsh", "powershell"}:
        return "'" + path.replace("'", "''") + "'"
    return "'" + path.replace("'", "'\\''") + "'"


def _in_grace(ws: Workspace, now: float) -> bool:
    """Just deactivated: output now is visit cleanup (the redraw tail,
    xterm settling), not news, so it flags nothing."""
    return ws.last_active_at is not None and now - ws.last_active_at < (
        UNSEEN_GRACE_SECONDS
    )


class AppController:
    """Owns AppState + live terminals.

    Locking rule: every public method takes ``self.lock`` itself (it's a
    reentrant lock, so nested calls are free) and holds it only around
    in-memory work — never across disk I/O, fsync, or a fork. Handlers
    running in worker threads may also take the lock around multi-step
    mutations; the reentrancy makes both compose.
    """

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
        self._busy_since: dict[str, float] = {}  # term id → busy since

    def save(self) -> None:
        if not self._persist:
            return
        # Snapshot under the lock (microseconds), write + fsync outside it:
        # a lock held across fsync stalls everyone waiting on it — including
        # the event loop via ``ensure_terminal`` — for the fsync duration.
        with self.lock:
            self._snapshot_cwds()
            payload = self.state.to_json()
        save_state_json(payload)

    def save_scrollback(self, tab_id: str, content: str) -> None:
        if not self._persist or not self.state.ui.scrollback_persist:
            return
        save_scrollback(tab_id, content)

    def load_scrollback(self, tab_id: str) -> str | None:
        if not self._persist or not self.state.ui.scrollback_persist:
            return None
        return load_scrollback(tab_id)

    def delete_scrollback(self, tab_id: str) -> None:
        # Ignores the ``scrollback_persist`` pref: it may have been turned
        # off mid-run, leaving a stale file behind.
        if self._persist:
            delete_scrollback(tab_id)

    def close_workspace(self, ws_id: str) -> bool:
        """Close a workspace: its shells, its tabs and their saved scrollback;
        False for an unknown one. The state keeps at least one workspace
        (``remove_workspace``)."""
        with self.lock:
            ws = self.state.get_workspace(ws_id)
            if ws is None:
                return False
            # Terminals first: removing the workspace drops its tabs.
            terms = [self._terminal_of(tid) for tid in ws.tab_ids]
            tab_ids = self.state.remove_workspace(ws_id)
            for term in terms:
                if term is not None:
                    self.terminals.close(term.id)
        # Disk is never touched under the lock.
        for tid in tab_ids:
            self.delete_scrollback(tid)
        self.save()
        return True

    def close_tab(self, tab_id: str) -> Literal["closed", "unknown", "last"]:
        """Close a tab: its shell and its saved scrollback. A workspace's
        last tab stays ("last"): closing it means closing the workspace."""
        with self.lock:
            term = self._terminal_of(tab_id)
            if tab_id not in self.state.tabs:
                return "unknown"
            if not self.state.remove_tab(tab_id):
                return "last"
            if term is not None:
                self.terminals.close(term.id)
        # Restart-in-place keeps the scrollback through its own endpoint;
        # a deliberate close drops it, outside the lock.
        self.delete_scrollback(tab_id)
        self.save()
        return "closed"

    def note_input(self, terminal_id: str) -> None:
        """Called when keystrokes arrive over a PTY WebSocket — the only
        signal we treat as "user is actually working here right now".
        Stamps the workspace that owns the terminal as last used."""
        self._last_input_at = time.monotonic()
        with self.lock:
            for ws in self.state.workspaces:
                if any(
                    (tab := self.state.tabs.get(tid)) is not None
                    and tab.terminal_id == terminal_id
                    for tid in ws.tab_ids
                ):
                    ws.last_used_at = time.time()
                    return

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
        with self.lock:
            return int(self._active_seconds.get(ws_id, 0.0))

    def reset_activity(self) -> None:
        """Clear all per-workspace counters and start a fresh session."""
        with self.lock:
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
            term = self._terminal_of(tab.id)
            if term is not None and (live := term.cwd()):
                tab.last_cwd = live

    def _terminal_of(self, tab_id: str | None) -> Terminal | None:
        """The tab's live terminal, if any (caller holds the lock)."""
        tab = self.state.tabs.get(tab_id) if tab_id is not None else None
        if tab is None or tab.terminal_id is None:
            return None
        return self.terminals.get(tab.terminal_id)

    async def ensure_terminal(
        self, tab_id: str, cols: int, rows: int
    ) -> Terminal | None:
        """Return the tab's live terminal, spawning a fresh shell if needed.

        Two-phase: the fork/exec/disk work runs in a worker thread so it
        can never stall the event loop; only attaching the reader (which
        must happen on the loop) runs here. Callers
        serialize through ``spawn_lock``, so the unlocked gap between the
        phases sees no concurrent spawn for the same tab.
        """
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:
                return None
            if tab.terminal_id is not None:
                existing = self.terminals.get(tab.terminal_id)
                if existing is not None and not existing.exited:
                    return existing
            spawn_cwd = tab.spawn_cwd

        def _spawn() -> PtyBackend:
            cwd = spawn_cwd or default_cwd()
            if not Path(cwd).is_dir():  # e.g. a restored dir since deleted
                cwd = default_cwd()
            return spawn_pty(default_shell(), cwd, cols, rows)

        pty = await asyncio.to_thread(_spawn)
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is None:  # tab closed while the shell was spawning
                pty.terminate()
                return None
            term = self.terminals.adopt(pty)
            tab.terminal_id = term.id
            term.on_activity = lambda: self._mark_activity(tab_id)
            term.on_attention = lambda: self._mark_ready(tab_id)
            term.on_exit = lambda _code: self._forget_terminal(tab_id, term.id)
            return term

    def _forget_terminal(self, tab_id: str, term_id: str) -> None:
        """The shell exited (on the loop): free its PTY and backlog. Clients
        already got the exit message; the next spawn for the tab starts a
        fresh shell."""
        with self.lock:
            tab = self.state.tabs.get(tab_id)
            if tab is not None and tab.terminal_id == term_id:
                tab.terminal_id = None
            self.terminals.close(term_id)
            self._busy_since.pop(term_id, None)

    def inherit_cwd(self, ws_id: str) -> str | None:
        """Working directory of a workspace's currently active live shell."""
        with self.lock:
            ws = self.state.get_workspace(ws_id)
            term = self._terminal_of(ws.active_tab_id) if ws is not None else None
            return term.cwd() if term is not None else None

    def active_terminal(self) -> Terminal | None:
        with self.lock:
            ws_id = self.state.active_workspace_id
            ws = self.state.get_workspace(ws_id) if ws_id else None
            return self._terminal_of(ws.active_tab_id) if ws is not None else None

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
                term = self._terminal_of(first_tid)
                # Refresh the active workspace's label, and fill in others'
                # once; ``cwd()`` costs a syscall or an lsof per call.
                fresh = ws.id == self.state.active_workspace_id or not tab.last_cwd
                if term is not None and fresh and (live := term.cwd()):
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
        pay the busy probe (a syscall) outside the ~2 Hz frontend poll.

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
                ws = by_id[wv["id"]]  # same state, same lock
                wv["name"] = self._workspace_label(ws)
                wv["active_seconds"] = self.active_seconds(ws.id)
                # Active/exited carry more urgent meaning and stay untouched.
                # Idle and unseen are both demoted to busy when any tab has
                # a foreground task running — UNLESS the workspace was just
                # deactivated: the visit-redraw tail / xterm settling would
                # otherwise paint the dot orange for the few seconds after
                # the user looked away.
                if (
                    wv["status"] in {WorkspaceStatus.IDLE, WorkspaceStatus.UNSEEN}
                    and not _in_grace(ws, now)
                    and any(
                        (term := self._terminal_of(tid)) is not None and term.is_busy()
                        for tid in ws.tab_ids
                    )
                ):
                    wv["status"] = WorkspaceStatus.BUSY.value
            return view

    def paste_paths(self, paths: list[str]) -> None:
        """Insert dropped file paths (shell-quoted) into the active terminal.

        Called from the pywebview thread; ``Terminal.write`` is safe across
        threads (a plain ``os.write`` on Unix, a locked write on Windows).
        """
        term = self.active_terminal()
        if term is None or not paths:
            return
        shell = default_shell()[0]
        text = " ".join(_shell_quote(p, shell) for p in paths) + " "
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
                if _in_grace(ws, now):
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
                if _in_grace(ws, now):
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
                    term = self._terminal_of(tid)
                    if term is None:
                        continue
                    is_busy_now = term.is_busy()
                    was_busy = term.id in self._busy_since
                    if is_busy_now and not was_busy:
                        self._busy_since[term.id] = now
                    elif was_busy and not is_busy_now:
                        since = self._busy_since.pop(term.id)
                        if now - since >= READY_TRANSITION_SECONDS:
                            self._mark_ready(tid)
