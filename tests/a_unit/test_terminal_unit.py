"""Deterministic Terminal/Subscriber tests using a fake PTY and loop."""

from __future__ import annotations

import asyncio

from terminux.core import terminal as term_mod
from terminux.core.terminal import Subscriber, Terminal


class _FakeLoop:
    def __init__(self, *, remove_raises: bool = False) -> None:
        self.remove_raises = remove_raises

    def add_reader(self, *_a) -> None:
        pass

    def remove_reader(self, *_a) -> None:
        if self.remove_raises:
            raise OSError


class _FakePty:
    fd = 7

    def __init__(self, code: int | None = 3) -> None:
        self._code = code

    def exit_code(self) -> int | None:
        return self._code


def _bare_terminal(loop: _FakeLoop, pty: _FakePty) -> Terminal:
    t = Terminal.__new__(Terminal)
    t.id = "x"
    t._pty = pty  # type: ignore[attr-defined]
    t._loop = loop  # type: ignore[attr-defined]
    t._backlog = bytearray()
    t._subscribers = set()
    t._exited = False
    t._exit_code = None
    t.on_activity = None
    t.on_attention = None
    t.on_exit = None
    t._attention = term_mod._AttentionScanner()
    return t


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
        assert s._pending == bytearray()

    asyncio.run(go())


# ----- Terminal fan-out (fake pty/loop) --------------------------------


def test_on_readable_feeds_subscribers_and_trims_backlog(monkeypatch) -> None:
    t = _bare_terminal(_FakeLoop(), _FakePty())
    sub = t.subscribe()
    seen = []
    t.on_activity = lambda: seen.append(1)
    monkeypatch.setattr(term_mod, "BACKLOG_CAP", 4)
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"abcdefgh")
    t._on_readable()
    assert sub._pending == bytearray(b"abcdefgh")
    assert len(t._backlog) == 4  # trimmed to cap
    assert seen == [1]


def test_on_readable_detects_bell_and_osc9(monkeypatch) -> None:
    t = _bare_terminal(_FakeLoop(), _FakePty())
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"plain output")
    t._on_readable()
    assert hits == []  # no BEL / OSC 9 → no attention

    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"done\x07")
    t._on_readable()
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]9;ready\x07")
    t._on_readable()
    assert hits == [1, 1]  # BEL and OSC 9 each fire it


def test_osc_title_bel_does_not_trigger_attention(monkeypatch) -> None:
    """The BEL that terminates an OSC 0/2 title isn't a real bell — Claude
    Code (and friends) update the title constantly while working, and that
    used to spam the sidebar."""
    t = _bare_terminal(_FakeLoop(), _FakePty())
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    # OSC 0;<title>BEL repeated — common for tools showing live state.
    monkeypatch.setattr(
        term_mod.os,
        "read",
        lambda *_a: b"\x1b]0;thinking\x07\x1b]0;tool: read\x07",
    )
    t._on_readable()
    # And an OSC terminated by the two-byte ST (ESC '\\') instead of BEL.
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]2;done\x1b\\")
    t._on_readable()
    assert hits == []


def test_osc_split_across_reads_does_not_fire(monkeypatch) -> None:
    """An OSC sequence spanning a chunk boundary must still suppress its
    terminating BEL."""
    t = _bare_terminal(_FakeLoop(), _FakePty())
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]0;par")
    t._on_readable()
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"tial\x07")
    t._on_readable()
    assert hits == []


def test_osc133_fires_only_for_long_commands(monkeypatch) -> None:
    """OSC 133;D ("command finished") fires attention only if the matching
    OSC 133;C happened long enough ago — a snappy `cd` shouldn't ring it."""
    t = _bare_terminal(_FakeLoop(), _FakePty())
    t.subscribe()
    hits = []
    t.on_attention = lambda: hits.append(1)

    # Pretend the scanner sees time advance between reads.
    clock = {"t": 1000.0}
    monkeypatch.setattr(term_mod.time, "monotonic", lambda: clock["t"])

    # Short command (< 2 s): C, then D ≈ 100 ms later → no fire.
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]133;C\x07")
    t._on_readable()
    clock["t"] += 0.1
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]133;D;0\x07")
    t._on_readable()
    assert hits == []

    # Long command: C, then D 5 s later → fires.
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]133;C\x07")
    t._on_readable()
    clock["t"] += 5.0
    monkeypatch.setattr(term_mod.os, "read", lambda *_a: b"\x1b]133;D;0\x07")
    t._on_readable()
    assert hits == [1]


def test_on_readable_oserror_triggers_eof() -> None:
    t = _bare_terminal(_FakeLoop(remove_raises=True), _FakePty(code=9))
    sub = t.subscribe()
    import unittest.mock as m

    with m.patch.object(term_mod.os, "read", side_effect=OSError):
        t._on_readable()
    assert t.exited is True
    assert t.exit_code == 9  # remove_reader OSError suppressed
    assert sub._closed is True


def test_handle_eof_idempotent_and_on_exit() -> None:
    codes: list[int | None] = []
    t = _bare_terminal(_FakeLoop(), _FakePty(code=5))
    t.on_exit = codes.append
    t._handle_eof()
    t._handle_eof()  # already exited -> early return
    assert codes == [5]


def test_subscribe_after_exit_is_closed_then_unsubscribe() -> None:
    t = _bare_terminal(_FakeLoop(), _FakePty())
    t._backlog += b"hi"
    t._exited = True
    sub = t.subscribe()
    assert sub._pending == bytearray(b"hi")  # backlog replayed
    assert sub._closed is True
    t.unsubscribe(sub)
    assert sub not in t._subscribers


def test_write_and_resize_after_exit_are_noops() -> None:
    t = _bare_terminal(_FakeLoop(), _FakePty())
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

    p = P()
    t = _bare_terminal(_FakeLoop(remove_raises=True), p)
    sub = t.subscribe()
    t.close()
    assert p.terminated is True
    assert sub._closed is True


def test_terminal_constructor_registers_reader() -> None:
    async def scenario() -> None:
        from pathlib import Path

        t = Terminal(["/bin/sh", "-c", "exit 0"], str(Path.cwd()), 80, 24)
        t.close()

    asyncio.run(scenario())
