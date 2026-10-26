"""Deterministic Terminal/Subscriber tests using a fake PTY and loop."""

from __future__ import annotations

import asyncio

from terminux.core import terminal as term_mod
from terminux.core.terminal import Subscriber, Terminal


class _FakePty:
    pid = 4242

    def __init__(self, code: int | None = 3) -> None:
        self._code = code
        self.sizes: list[tuple[int, int]] = []  # every resize, in order
        self.busy: bool | None = False  # what foreground_busy() reports
        self.attached: object = None
        self.detached = 0
        self.cwd_value: str | None = None

    def attach(self, loop: object, on_data: object) -> None:
        self.attached = on_data

    def detach(self) -> None:
        self.detached += 1

    def foreground_busy(self) -> bool | None:
        return self.busy

    def cwd(self) -> str | None:
        return self.cwd_value

    def exit_code(self) -> int | None:
        return self._code

    def resize(self, cols: int, rows: int) -> None:
        self.sizes.append((cols, rows))


def _drained(sub: Subscriber) -> bytes:
    return asyncio.run(sub.drain())[1]


def _terminal(pty: _FakePty | None = None) -> Terminal:
    """A real Terminal, built on a throwaway loop: the fake PTY never
    schedules anything on it."""

    async def build() -> Terminal:
        return Terminal(pty or _FakePty())  # type: ignore[arg-type]

    return asyncio.run(build())


# ----- Subscriber ------------------------------------------------------


def test_subscriber_batches_and_drains() -> None:
    async def go() -> None:
        s = Subscriber()
        s.feed(b"ab")
        s.feed(b"cd")  # coalesced into one drain
        dropped, data, closed = await s.drain()
        assert (dropped, data, closed) == (False, b"abcd", False)

    asyncio.run(go())


def test_subscriber_backpressure_drops(monkeypatch) -> None:
    monkeypatch.setattr(term_mod, "OUTBOUND_CAP", 8)
    monkeypatch.setattr(term_mod, "FLUSH_INTERVAL", 0)

    async def go() -> None:
        s = Subscriber()
        s.feed(b"1234")
        s.feed(b"567890")  # 4 + 6 > cap(8) -> drop, keep tail
        dropped, data, closed = await s.drain()
        assert dropped is True
        assert data == b"567890"  # backlog discarded, recent tail kept
        assert closed is False

    asyncio.run(go())


def test_subscriber_close_drains_closed() -> None:
    async def go() -> None:
        s = Subscriber()
        s.feed(b"tail")
        s.close()
        _dropped, data, closed = await s.drain()
        assert closed is True
        assert data == b"tail"
        s.feed(b"ignored after close")
        s.close()  # wakes drain again
        assert await s.drain() == (False, b"", True)

    asyncio.run(go())


# ----- Terminal fan-out (fake pty/loop) --------------------------------


def test_on_data_feeds_subscribers_and_trims_backlog(monkeypatch) -> None:
    t = _terminal()
    sub = t.subscribe()
    seen = []
    t.on_activity = lambda: seen.append(1)
    monkeypatch.setattr(term_mod, "BACKLOG_CAP", 4)
    t._on_data(b"abcdefgh")
    assert _drained(sub) == b"abcdefgh"
    assert _drained(t.subscribe()) == b"efgh"  # the replayed backlog is capped
    assert seen == [1]


def test_on_data_detects_bell_and_osc9() -> None:
    t = _terminal()
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    t._on_data(b"plain output")
    assert hits == []  # no BEL / OSC 9 → no attention

    t._on_data(b"done\x07")
    t._on_data(b"\x1b]9;ready\x07")
    assert hits == [1, 1]  # BEL and OSC 9 each fire it


def test_osc_title_bel_does_not_trigger_attention(monkeypatch) -> None:
    """The BEL that terminates an OSC 0/2 title isn't a real bell — Claude
    Code (and friends) update the title constantly while working, and that
    used to spam the sidebar."""
    t = _terminal()
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    # OSC 0;<title>BEL repeated — common for tools showing live state.
    t._on_data(b"\x1b]0;thinking\x07\x1b]0;tool: read\x07")
    # And an OSC terminated by the two-byte ST (ESC '\\') instead of BEL.
    t._on_data(b"\x1b]2;done\x1b\\")
    assert hits == []


def test_osc_split_across_reads_does_not_fire(monkeypatch) -> None:
    """An OSC sequence spanning a chunk boundary must still suppress its
    terminating BEL."""
    t = _terminal()
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    t._on_data(b"\x1b]0;par")
    t._on_data(b"tial\x07")
    assert hits == []


def test_is_busy_asks_the_backend_when_no_osc133() -> None:
    """Without shell integration, is_busy() asks the backend whether a
    command is in the foreground (tcgetpgrp on Unix, a child process on
    Windows)."""
    pty = _FakePty()
    t = _terminal(pty)

    pty.busy = False
    assert t.is_busy() is False  # the shell is at its prompt → ready

    pty.busy = True
    assert t.is_busy() is True  # something else is foregrounded → busy

    pty.busy = None  # the backend can't tell → never busy
    assert t.is_busy() is False

    # An exited terminal is never busy whatever the backend says.
    t._exited = True
    pty.busy = True
    assert t.is_busy() is False


def test_is_busy_trusts_osc133_once_seen() -> None:
    """Once any OSC 133 sequence has come through, the OSC state takes
    precedence over the backend — the shell is the authoritative source."""
    pty = _FakePty()
    t = _terminal(pty)
    # The backend would say "busy", but we'll override via OSC 133.
    pty.busy = True

    # OSC 133;C → inside a command → busy, regardless of the backend.
    t._on_data(b"\x1b]133;C\x07")
    assert t.is_busy() is True

    # OSC 133;D → back at the prompt → ready, even though the backend lies.
    t._on_data(b"\x1b]133;D;0\x07")
    assert t.is_busy() is False


def test_is_busy_requires_recent_output() -> None:
    """A foreground child without recent PTY output is treated as
    quiescent — covers parked TUIs (Claude Code waiting for input,
    idle vim) that would otherwise keep the kernel signal lit
    forever even though nothing is happening."""
    import time

    pty = _FakePty()
    t = _terminal(pty)
    pty.busy = True  # the kernel says a command is in the foreground

    # Recent output → busy.
    t._last_output_at = time.monotonic()
    assert t.is_busy() is True

    # Silent past the threshold → not busy, even with a foreground child.
    t._last_output_at = time.monotonic() - term_mod.BUSY_IDLE_THRESHOLD - 1
    assert t.is_busy() is False


def test_is_busy_recovers_from_stuck_osc133() -> None:
    """A shell that emits ``OSC 133;C`` but never the matching ``;D``
    used to keep the workspace amber forever; the recent-output veto
    now releases it once the workspace falls silent."""
    import time

    t = _terminal()
    t._on_data(b"\x1b]133;C\x07")  # a command starts; no ;D ever comes

    t._last_output_at = time.monotonic()
    assert t.is_busy() is True  # output still flowing

    t._last_output_at = time.monotonic() - term_mod.BUSY_IDLE_THRESHOLD - 1
    assert t.is_busy() is False  # silent → release the dot


def test_osc133_fires_only_for_long_commands(monkeypatch) -> None:
    """OSC 133;D ("command finished") fires attention only if the matching
    OSC 133;C happened long enough ago — a snappy `cd` shouldn't ring it."""
    t = _terminal()
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    # Pretend the scanner sees time advance between reads.
    clock = {"t": 1000.0}
    monkeypatch.setattr(term_mod.time, "monotonic", lambda: clock["t"])

    # Short command (< 2 s): C, then D ≈ 100 ms later → no fire.
    t._on_data(b"\x1b]133;C\x07")
    clock["t"] += 0.1
    t._on_data(b"\x1b]133;D;0\x07")
    assert hits == []

    # Long command: C, then D 5 s later → fires.
    t._on_data(b"\x1b]133;C\x07")
    clock["t"] += 5.0
    t._on_data(b"\x1b]133;D;0\x07")
    assert hits == [1]


def test_on_data_eof_detaches_and_closes() -> None:
    pty = _FakePty(code=9)
    t = _terminal(pty)
    sub = t.subscribe()
    t._on_data(b"")
    assert t.exited is True
    assert t.exit_code == 9
    assert pty.detached == 1
    assert asyncio.run(sub.drain())[2] is True  # closed


def test_constructor_attaches_the_backend() -> None:
    async def scenario() -> None:
        pty = _FakePty()
        t = Terminal(pty)  # type: ignore[arg-type]
        assert pty.attached == t._on_data

    asyncio.run(scenario())


# ----- OSC 9 subcommands and cwd reports --------------------------------


def test_conemu_osc9_subcommands_are_not_notifications() -> None:
    """``OSC 9;4`` (progress: winget, …) and ``OSC 9;9`` (cwd) came at every
    prompt and lit the attention dot; only a plain ``OSC 9;<msg>`` counts."""
    t = _terminal()
    hits = []
    t.on_attention = lambda: hits.append(1)
    t._on_data(b"\x1b]9;4;1;50\x07\x1b]9;9;C:\\x\x07\x1b]9;12\x07\x1b]9;1;2\x07")
    assert hits == []
    t._on_data(b"\x1b]9;10 files copied\x07")  # a message starting with a digit
    t._on_data(b"\x1b]9;42;answer\x07")  # not a ConEmu subcommand number
    assert hits == [1, 1]


def test_cwd_falls_back_to_what_the_shell_reports() -> None:
    pty = _FakePty()  # like Windows: the backend can't tell
    t = _terminal(pty)
    assert t.cwd() is None
    t._on_data(b'\x1b]9;9;"C:\\Users\\me"\x07')
    assert t.cwd() == "C:\\Users\\me"
    t._on_data(b"\x1b]7;file://host/home/me/a%20b\x1b\\")
    assert t.cwd() == "/home/me/a b"


def test_the_kernel_cwd_wins_over_a_reported_one() -> None:
    """A reported cwd can be stale (an ssh session reports the remote
    host's), so it's only used when the backend can't tell."""
    pty = _FakePty()
    pty.cwd_value = "/local"
    t = _terminal(pty)
    t._on_data(b"\x1b]7;file://remote/srv\x07")
    assert t.cwd() == "/local"


def test_cwd_report_split_across_reads_and_too_long() -> None:
    t = _terminal()
    t._on_data(b"\x1b]7;file://h/a-very-long-dir")
    t._on_data(b"ectory/name\x07")
    assert t._attention.reported_cwd == "/a-very-long-directory/name"
    t._on_data(b"\x1b]7;file://h/" + b"x" * 5000 + b"\x07")
    assert t._attention.reported_cwd == "/a-very-long-directory/name"  # ignored
    t._on_data(b"\x1b]7;file:///C:/Users/me\x07")
    assert t._attention.reported_cwd == "C:/Users/me"


def test_cwd_from_osc_rejects_junk() -> None:
    assert term_mod._cwd_from_osc(b"7;http://h/x") is None
    assert term_mod._cwd_from_osc(b"7;file://h") is None
    assert term_mod._cwd_from_osc(b"9;9;") is None
    assert term_mod._cwd_from_osc(b"7;file://h/\xff") is None


def test_handle_eof_idempotent_and_on_exit() -> None:
    codes: list[int | None] = []
    t = _terminal(_FakePty(code=5))
    t.on_exit = codes.append
    t._handle_eof()
    t._handle_eof()  # already exited -> early return
    assert codes == [5]


def test_subscribe_after_exit_is_closed_then_unsubscribe() -> None:
    t = _terminal()
    t._on_data(b"hi")
    t._on_data(b"")  # EOF: the shell exited
    sub = t.subscribe()
    assert asyncio.run(sub.drain()) == (False, b"hi", True)  # backlog, closed
    t.unsubscribe(sub)
    assert sub not in t._subscribers


def test_write_and_resize_after_exit_are_noops() -> None:
    t = _terminal()
    t._exited = True
    t.write(b"data")
    t.resize(10, 10)


def test_close_marks_subscribers_closed() -> None:
    class P(_FakePty):
        def __init__(self) -> None:
            super().__init__()
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

    async def go(close_from_worker: bool) -> None:
        p = P()
        t = Terminal(p)  # type: ignore[arg-type]
        sub = t.subscribe()
        if close_from_worker:  # as a sync request handler does
            await asyncio.to_thread(t.close)
        else:
            t.close()
        assert (await sub.drain())[2] is True  # closed, and the drain woke
        assert p.terminated is True
        assert p.detached == 1

    asyncio.run(go(close_from_worker=False))
    asyncio.run(asyncio.wait_for(go(close_from_worker=True), timeout=2))


# ----- ownership (several clients, one PTY size) ------------------------


def _owner_news(*subs: Subscriber) -> list[bool | None]:
    return [s.take_owner_news() for s in subs]


def test_first_client_owns_and_later_ones_watch() -> None:
    t = _terminal()
    desk, laptop = t.subscribe(), t.subscribe()
    assert _owner_news(desk, laptop) == [True, False]
    assert t.is_owner(desk)
    assert not t.is_owner(laptop)


def test_a_watcher_attaching_never_resizes_the_owners_screen() -> None:
    """The reported bug: the --connect window sent its size on attach and
    re-flowed the desktop's screen. Now only the owner's size applies."""
    pty = _FakePty()
    t = _terminal(pty)
    desk, laptop = t.subscribe(), t.subscribe()
    t.report_size(desk, 200, 50)
    t.report_size(laptop, 120, 35)  # recorded, not applied
    assert pty.sizes == [(200, 50)]
    assert laptop.size == (120, 35)


def test_claiming_moves_ownership_and_size() -> None:
    pty = _FakePty()
    t = _terminal(pty)
    desk, laptop = t.subscribe(), t.subscribe()
    t.report_size(desk, 200, 50)
    t.report_size(laptop, 120, 35)
    _owner_news(desk, laptop)  # clear the attach-time news

    t.claim(laptop)  # the user switches to the laptop
    assert pty.sizes[-1] == (120, 35)
    assert _owner_news(desk, laptop) == [False, True]

    t.claim(desk)  # ...and comes back to the desktop
    assert pty.sizes[-1] == (200, 50)
    assert _owner_news(desk, laptop) == [True, False]


def test_claiming_what_you_already_own_changes_nothing() -> None:
    pty = _FakePty()
    t = _terminal(pty)
    desk = t.subscribe()
    t.report_size(desk, 200, 50)
    _owner_news(desk)
    t.claim(desk)
    assert pty.sizes == [(200, 50)]
    assert _owner_news(desk) == [None]


def test_when_the_owner_leaves_the_latest_watcher_takes_over() -> None:
    pty = _FakePty()
    t = _terminal(pty)
    a, b, c = t.subscribe(), t.subscribe(), t.subscribe()
    for sub, size in ((a, (200, 50)), (b, (80, 24)), (c, (120, 35))):
        t.report_size(sub, *size)
    _owner_news(a, b, c)

    t.unsubscribe(a)  # the owner's window closes
    assert t.is_owner(c)  # most recently attached
    assert pty.sizes[-1] == (120, 35)
    assert _owner_news(b, c) == [None, True]


def test_after_the_last_client_leaves_the_next_one_owns() -> None:
    t = _terminal()
    only = t.subscribe()
    t.unsubscribe(only)
    nxt = t.subscribe()
    assert t.is_owner(nxt)
    assert _owner_news(nxt) == [True]


def test_replay_end_is_reported_once_per_subscriber() -> None:
    t = _terminal()
    t._on_data(b"\x1b[c")  # a query in the backlog the next client replays
    sub = t.subscribe()
    assert sub.take_replay_end() is True
    assert sub.take_replay_end() is False
    assert t.subscribe().take_replay_end() is True  # every client gets one


def test_only_the_first_client_answers_the_backlog() -> None:
    t = _terminal()
    first, later = t.subscribe(), t.subscribe()
    t.unsubscribe(first)
    t.unsubscribe(later)
    assert (first.first, later.first, t.subscribe().first) == (True, False, False)
