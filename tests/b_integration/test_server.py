"""Integration tests exercising every HTTP/WebSocket handler."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import websockets
from starlette.routing import Route

from terminux.server.asgi import build_app
from terminux.server.auth import SESSION_TOKEN
from tests.conftest import wait_until

if TYPE_CHECKING:
    from tests.conftest import LiveServer

T = SESSION_TOKEN


def _req(url: str, method: str = "GET", body: bytes | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, method=method, data=body)  # noqa: S310
    with urllib.request.urlopen(req) as r:  # noqa: S310
        raw = r.read()
    return json.loads(raw) if raw else {}


def _get(url: str) -> Any:
    with urllib.request.urlopen(url) as r:  # noqa: S310
        return r.read()


# ----- token guard -----------------------------------------------------


def _guarded_routes() -> list[tuple[str, str]]:
    """Every HTTP route and method the app serves (so a new route is
    covered automatically), with path parameters filled in."""
    cases = []
    for route in build_app(persist=False).routes:
        if isinstance(route, Route):
            path = re.sub(r"\{[^}]+\}", "x", route.path)
            cases += [(path, m) for m in sorted(route.methods or ()) if m != "HEAD"]
    return cases


@pytest.mark.parametrize(("path", "method"), _guarded_routes())
def test_endpoints_require_token(server: LiveServer, path: str, method: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(f"{server.url}{path}", method=method, body=b"{}")
    assert exc.value.code == 403


# ----- static ----------------------------------------------------------


def test_index_serves_built_bundle_with_token(server: LiveServer) -> None:
    index = _get(f"{server.url}/?t={T}").decode()
    assert "<title>terminux</title>" in index
    # The placeholder is replaced with the live session token.
    assert "__TOKEN__" not in index
    assert SESSION_TOKEN in index
    # The Vite-built, content-hashed JS/CSS assets are served under /assets.
    refs = re.findall(r'/assets/[^"\']+', index)
    assert any(r.endswith(".js") for r in refs)
    assert any(r.endswith(".css") for r in refs)
    for ref in refs:
        body = _get(f"{server.url}{ref}")
        assert body  # 200 with content (urlopen raises on non-2xx)


def test_security_headers_present(server: LiveServer) -> None:
    with urllib.request.urlopen(f"{server.url}/?t={T}") as r:  # noqa: S310
        headers = r.headers
    csp = headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'none'" in csp
    assert "connect-src 'self'" in csp
    # Older WebKit/Firefox don't count same-origin ws under 'self' — the ws
    # origin must be named explicitly or the PTY socket is refused
    # (observed on macOS Big Sur's WKWebView).
    host = server.url.removeprefix("http://")
    assert f"ws://{host}" in csp
    assert f"wss://{host}" in csp
    # Regression guard: pywebview's evaluate_js needs 'unsafe-eval'.
    assert "'unsafe-eval'" in csp
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"


# ----- workspace / tab control plane -----------------------------------


def _patch(url: str, body: dict[str, Any]) -> None:
    _req(url, "PATCH", json.dumps(body).encode())


def test_new_workspace_becomes_active(server: LiveServer) -> None:
    base = server.url
    assert len(_req(f"{base}/api/state?t={T}")["workspaces"]) == 1
    ws1 = _req(f"{base}/api/workspaces?t={T}", "POST", b"{}")["id"]
    st = _req(f"{base}/api/state?t={T}")
    assert len(st["workspaces"]) == 2
    assert st["active_workspace_id"] == ws1


def test_workspace_rename_and_reorder(server: LiveServer) -> None:
    base = server.url
    ws0 = _req(f"{base}/api/state?t={T}")["workspaces"][0]["id"]
    ws1 = _req(f"{base}/api/workspaces?t={T}", "POST", b"{}")["id"]
    _patch(f"{base}/api/workspaces/{ws1}?t={T}", {"name": "renamed", "active": True})
    _patch(f"{base}/api/workspaces/{ws0}?t={T}", {"order": [ws1, ws0]})
    st = _req(f"{base}/api/state?t={T}")
    assert {w["id"]: w["name"] for w in st["workspaces"]}[ws1] == "renamed"
    assert [w["id"] for w in st["workspaces"]] == [ws1, ws0]


def test_tab_rename_and_delete(server: LiveServer) -> None:
    base = server.url
    ws = _req(f"{base}/api/state?t={T}")["workspaces"][0]["id"]
    tab = _req(f"{base}/api/workspaces/{ws}/tabs?t={T}", "POST", b"{}")["id"]
    _patch(f"{base}/api/tabs/{tab}?t={T}", {"title": "logs"})
    assert _req(f"{base}/api/state?t={T}")["tabs"][tab]["title"] == "logs"
    _req(f"{base}/api/tabs/{tab}?t={T}", "DELETE", b"{}")
    assert tab not in _req(f"{base}/api/state?t={T}")["tabs"]


def test_active_tab_id_can_be_set_and_cleared(server: LiveServer) -> None:
    base = server.url
    ws = _req(f"{base}/api/state?t={T}")["workspaces"][0]["id"]
    tab = _req(f"{base}/api/workspaces/{ws}/tabs?t={T}", "POST", b"{}")["id"]

    def active_tab() -> str | None:
        st = _req(f"{base}/api/state?t={T}")
        return next(w for w in st["workspaces"] if w["id"] == ws)["active_tab_id"]

    _patch(f"{base}/api/workspaces/{ws}?t={T}", {"active_tab_id": tab})
    assert active_tab() == tab
    _patch(f"{base}/api/workspaces/{ws}?t={T}", {"active_tab_id": None})
    assert active_tab() is None


def test_workspace_label_tracks_cwd_then_pins(server: LiveServer) -> None:
    """/api/state shows the active shell's dir; rename pins it."""
    base = server.url
    ctl = server.controller
    target = Path(tempfile.mkdtemp()).resolve()
    ws0 = ctl.state.workspaces[0]
    ctl.state.tabs[ws0.active_tab_id].spawn_cwd = str(target)
    _req(f"{base}/api/tabs/{ws0.active_tab_id}/spawn?t={T}", "POST", b"{}")
    term = ctl.active_terminal()
    assert term is not None
    wait_until(lambda: term.cwd() == str(target))

    name = _req(f"{base}/api/state?t={T}")["workspaces"][0]["name"]
    assert name == target.name

    # Renaming pins it: the label stops tracking cwd.
    _req(
        f"{base}/api/workspaces/{ws0.id}?t={T}",
        "PATCH",
        json.dumps({"name": "pinned"}).encode(),
    )
    assert _req(f"{base}/api/state?t={T}")["workspaces"][0]["name"] == "pinned"


def test_tab_osc_title_tracks_until_pinned(server: LiveServer) -> None:
    base = server.url
    tab = _req(f"{base}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]

    def title() -> str:
        return _req(f"{base}/api/state?t={T}")["tabs"][tab]["title"]

    _req(
        f"{base}/api/tabs/{tab}?t={T}",
        "PATCH",
        json.dumps({"osc_title": "vim"}).encode(),
    )
    assert title() == "vim"
    _req(
        f"{base}/api/tabs/{tab}?t={T}",
        "PATCH",
        json.dumps({"osc_title": "less"}).encode(),
    )
    assert title() == "less"
    # Explicit rename pins it; later OSC titles are ignored.
    _req(
        f"{base}/api/tabs/{tab}?t={T}", "PATCH", json.dumps({"title": "logs"}).encode()
    )
    assert title() == "logs"
    _req(
        f"{base}/api/tabs/{tab}?t={T}",
        "PATCH",
        json.dumps({"osc_title": "sh"}).encode(),
    )
    assert title() == "logs"


def test_patch_ui_clamps_and_persists(server: LiveServer) -> None:
    base = server.url

    def ui() -> dict[str, Any]:
        return _req(f"{base}/api/state?t={T}")["ui"]

    assert ui()["sidebar_width"] == 220
    _req(f"{base}/api/ui?t={T}", "PATCH", json.dumps({"sidebar_width": 9999}).encode())
    assert ui()["sidebar_width"] == 600  # clamped to max
    _req(f"{base}/api/ui?t={T}", "PATCH", json.dumps({"sidebar_width": 10}).encode())
    assert ui()["sidebar_width"] == 120  # clamped to min
    _req(
        f"{base}/api/ui?t={T}",
        "PATCH",
        json.dumps({"win_w": 1280, "win_h": 800, "win_x": 10, "win_y": 20}).encode(),
    )
    u = ui()
    assert (u["win_w"], u["win_h"], u["win_x"], u["win_y"]) == (1280, 800, 10, 20)
    # Font zoom + sidebar collapsed persist here (localStorage can't —
    # the loopback port changes every launch).
    _req(f"{base}/api/ui?t={T}", "PATCH", json.dumps({"font_size": 999}).encode())
    assert ui()["font_size"] == 32  # clamped to max
    _req(f"{base}/api/ui?t={T}", "PATCH", json.dumps({"font_size": 17}).encode())
    assert ui()["font_size"] == 17
    _req(
        f"{base}/api/ui?t={T}",
        "PATCH",
        json.dumps({"sidebar_collapsed": True}).encode(),
    )
    assert ui()["sidebar_collapsed"] is True
    # copy_on_select defaults off and round-trips.
    assert ui()["copy_on_select"] is False
    _req(
        f"{base}/api/ui?t={T}",
        "PATCH",
        json.dumps({"copy_on_select": True}).encode(),
    )
    assert ui()["copy_on_select"] is True


def test_scrollback_endpoints(
    server: LiveServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = server.url
    st = _req(f"{base}/api/state?t={T}")
    tab_id = st["workspaces"][0]["tab_ids"][0]

    # Wire up file-backed storage in a tmp dir so we can verify lifecycle.
    # ``monkeypatch`` restores both the persistence path and the controller's
    # ``_persist`` flag at end-of-test, so no manual try/finally is needed.
    from terminux.core import persistence

    monkeypatch.setattr(server.controller, "_persist", True)
    monkeypatch.setattr(persistence, "state_path", lambda: tmp_path / "state.json")

    url = f"{base}/api/tabs/{tab_id}/scrollback?t={T}"
    # No file yet — GET returns 200 with empty body.
    assert _get(url) == b""
    # PUT then GET round-trip.
    urllib.request.urlopen(  # noqa: S310
        urllib.request.Request(  # noqa: S310
            url,
            method="PUT",
            data=b"hello\x1b[1mworld\x1b[0m",
        ),
    ).read()
    assert _get(url) == b"hello\x1b[1mworld\x1b[0m"
    # DELETE then GET → empty again.
    _req(url, "DELETE", b"")
    assert _get(url) == b""
    # Deleting the tab purges its scrollback.
    urllib.request.urlopen(  # noqa: S310
        urllib.request.Request(url, method="PUT", data=b"more"),  # noqa: S310
    ).read()
    _req(f"{base}/api/tabs/{tab_id}?t={T}", "DELETE")
    # GET on a gone tab is 404.
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(url)
    assert exc.value.code == 404
    # No scrollback files left behind.
    sb = tmp_path / "scrollback"
    assert not sb.exists() or not list(sb.glob("*.ansi"))

    # Opt-out: with scrollback_persist disabled, PUT is a silent no-op.
    ws_id = _req(f"{base}/api/state?t={T}")["workspaces"][0]["id"]
    new_tab = _req(
        f"{base}/api/workspaces/{ws_id}/tabs?t={T}",
        "POST",
        b"{}",
    )["id"]
    _req(
        f"{base}/api/ui?t={T}",
        "PATCH",
        json.dumps({"scrollback_persist": False}).encode(),
    )
    new_url = f"{base}/api/tabs/{new_tab}/scrollback?t={T}"
    urllib.request.urlopen(  # noqa: S310
        urllib.request.Request(new_url, method="PUT", data=b"silenced"),  # noqa: S310
    ).read()
    assert _get(new_url) == b""


def test_open_url_validates_scheme_and_requires_token(server: LiveServer) -> None:
    base = server.url

    # Token guard.
    req = urllib.request.Request(  # noqa: S310
        f"{base}/api/open-url",
        method="POST",
        data=json.dumps({"url": "https://example.com"}).encode(),
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)  # noqa: S310
    assert exc.value.code == 403

    # Reject dangerous schemes (file://, javascript:, data:…).
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,x", ""):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _req(
                f"{base}/api/open-url?t={T}",
                "POST",
                json.dumps({"url": bad}).encode(),
            )
        assert exc.value.code == 400

    # Patch the opener so the test never actually spawns `open`. The
    # handler in api.py uses its own module-level binding; that's the
    # one we need to swap.
    from terminux.server import api

    calls: list[str] = []
    monkey = api.open_url_in_default_app
    api.open_url_in_default_app = lambda u: (calls.append(u), True)[1]  # type: ignore[assignment]
    try:
        _req(
            f"{base}/api/open-url?t={T}",
            "POST",
            json.dumps({"url": "https://example.com/path?x=1"}).encode(),
        )
        assert calls == ["https://example.com/path?x=1"]
    finally:
        api.open_url_in_default_app = monkey  # type: ignore[assignment]


def test_stress_blocking_pty_write_does_not_freeze_server(  # noqa: PLR0914
    server: LiveServer, caplog
) -> None:
    """Stress regression test for the second observed freeze.

    A blocking ``os.write`` on the PTY master used to be called directly
    from the asyncio loop thread inside ``_pump_in``. With the fix the
    write is offloaded via ``asyncio.to_thread``, so a stuck shell can
    still block one worker thread — but the event loop stays free.

    This test proves three invariants under simulated load:

    1. **Loop liveness** — concurrent ``GET /api/state`` requests complete
       with low latency while a PTY write is parked.
    2. **Bounded blast radius** — a second terminal sees its writes go
       through while the first one is stuck.
    3. **Watchdog silence** — ``terminux.diagnostics`` never emits its
       "event loop unresponsive" warning during the scenario.

    Without the fix every HTTP request and every other PTY's pump would
    grind to a halt for the duration of the slow write, the watchdog
    would fire at the 3 s mark, and assertion (1) would fail with
    multi-second latencies.
    """
    import logging
    import threading

    base = server.url
    ctl = server.controller

    # Two real terminals: ``stuck_tid`` will receive the blocked write,
    # ``free_tid`` will be exercised concurrently.
    tab = _req(f"{base}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]
    stuck_tid = _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")["terminal_id"]

    extra_ws = _req(f"{base}/api/workspaces?t={T}", "POST", b"{}")["id"]
    extra_tab = next(
        w for w in _req(f"{base}/api/state?t={T}")["workspaces"] if w["id"] == extra_ws
    )["tab_ids"][0]
    free_tid = _req(f"{base}/api/tabs/{extra_tab}/spawn?t={T}", "POST", b"{}")[
        "terminal_id"
    ]

    stuck = ctl.terminals.get(stuck_tid)
    free = ctl.terminals.get(free_tid)
    assert stuck is not None
    assert free is not None

    # Simulate a kernel PTY buffer full of unread bytes: replace the
    # stuck terminal's underlying ``_pty.write`` with one that parks for
    # ``BLOCK_SECONDS``. The free terminal's write stays untouched.
    block_seconds = 4.0
    write_started = threading.Event()
    write_count = [0]
    original_write = stuck._pty.write

    def slow_write(_data: bytes) -> None:
        write_count[0] += 1
        write_started.set()
        time.sleep(block_seconds)

    stuck._pty.write = slow_write  # type: ignore[method-assign]

    stuck_ws = base.replace("http", "ws") + f"/pty/{stuck_tid}?t={T}"
    free_ws = base.replace("http", "ws") + f"/pty/{free_tid}?t={T}"

    async def scenario() -> tuple[list[float], int, int]:
        async with websockets.connect(stuck_ws) as stuck_conn:
            # Trigger the slow write — server-side, this lands on a
            # worker thread (via asyncio.to_thread). Without the fix
            # it would run directly on the event loop thread.
            await stuck_conn.send(b"x" * 256)

            # Wait until the worker thread is actually inside slow_write,
            # so the rest of the scenario unambiguously runs during the
            # blocked window.
            assert write_started.wait(timeout=2.0), "slow write never reached"

            loop = asyncio.get_running_loop()

            async def state_call() -> float:
                start = time.monotonic()
                await loop.run_in_executor(None, _req, f"{base}/api/state?t={T}")
                return time.monotonic() - start

            # 1. Hammer the HTTP control plane with concurrent state polls
            #    while the PTY write is parked.
            latencies = await asyncio.gather(*(state_call() for _ in range(30)))

            # 2. While the first terminal is stuck, the second one's
            #    write path must still work end-to-end. We can prove
            #    this end-to-end by connecting to ``free_tid``'s
            #    WebSocket and sending a frame: if ``_pump_in`` were
            #    blocked, this send would never be processed.
            free_writes_accepted = 0
            async with websockets.connect(free_ws) as free_conn:
                for _ in range(5):
                    await free_conn.send(b"echo ok\n")
                    free_writes_accepted += 1

            return latencies, free_writes_accepted, write_count[0]

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="terminux.diagnostics"):
        try:
            latencies, free_writes, n_writes = asyncio.run(
                asyncio.wait_for(scenario(), timeout=block_seconds + 10)
            )
        finally:
            # The stuck write is still parked; restore the real write
            # before cleanup (even on failure) so teardown doesn't block.
            stuck._pty.write = original_write  # type: ignore[method-assign]

    # Invariant 1: loop stayed responsive. The fix gives single-digit ms
    # per state call; without the fix latency would balloon past
    # ``block_seconds``. The budget is set well below ``block_seconds``
    # but above realistic in-process HTTP latency.
    assert latencies, "no state calls completed"
    p99 = max(latencies)
    assert p99 < block_seconds / 2, (
        f"p99 /api/state latency was {p99 * 1000:.0f}ms — event loop likely "
        f"blocked. Latencies (ms): "
        f"{[round(latency * 1000, 1) for latency in latencies]}"
    )

    # Invariant 2: the other terminal stayed usable.
    assert free_writes == 5

    # Sanity: the slow write actually ran (only once — the WebSocket
    # delivered one frame; if zero, we'd be testing nothing).
    assert n_writes == 1

    # Invariant 3: the watchdog did not fire. If it did, the loop must
    # have been blocked for >= STALL_THRESHOLD (3s) — i.e. the fix
    # regressed and the test should fail loudly.
    watchdog_warnings = [
        r for r in caplog.records if "event loop unresponsive" in r.message
    ]
    assert not watchdog_warnings, (
        f"watchdog fired {len(watchdog_warnings)} time(s) — event loop "
        f"stalled past STALL_THRESHOLD"
    )


def test_paste_paths_endpoint_writes_to_active_terminal(
    server: LiveServer, tmp_path: Any
) -> None:
    """``POST /api/paste-paths`` is the remote-mode equivalent of the
    local drag-and-drop bridge: the body's paths get shell-quoted and
    written to the active terminal."""
    base = server.url
    ctl = server.controller
    ws = ctl.state.workspaces[0]
    ctl.state.tabs[ws.active_tab_id].spawn_cwd = str(tmp_path)
    _req(f"{base}/api/tabs/{ws.active_tab_id}/spawn?t={T}", "POST", b"{}")

    term = ctl.active_terminal()
    assert term is not None

    # Capture writes instead of letting them hit the PTY, so we can assert
    # on the exact byte sequence the handler emits.
    written: list[bytes] = []
    term.write = written.append  # type: ignore[method-assign]

    # Token guard first.
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(
            f"{base}/api/paste-paths",
            "POST",
            json.dumps({"paths": ["/a.txt"]}).encode(),
        )
    assert exc.value.code == 403

    # Bad body shape.
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(
            f"{base}/api/paste-paths?t={T}",
            "POST",
            json.dumps({"paths": "not-a-list"}).encode(),
        )
    assert exc.value.code == 400

    # Happy path — paths get shell-quoted (including the space) and a
    # trailing space is appended for easy chaining at the prompt.
    _req(
        f"{base}/api/paste-paths?t={T}",
        "POST",
        json.dumps({"paths": ["/a b/c.txt", "/d.txt"]}).encode(),
    )
    assert written == [b"'/a b/c.txt' '/d.txt' "]


def test_tab_order_reorders_and_sanitizes(server: LiveServer) -> None:
    base = server.url
    st = _req(f"{base}/api/state?t={T}")
    ws = st["workspaces"][0]["id"]
    t0 = st["workspaces"][0]["tab_ids"][0]
    t1 = _req(f"{base}/api/workspaces/{ws}/tabs?t={T}", "POST", b"{}")["id"]
    t2 = _req(f"{base}/api/workspaces/{ws}/tabs?t={T}", "POST", b"{}")["id"]

    def tab_ids() -> list[str]:
        s = _req(f"{base}/api/state?t={T}")
        return next(w for w in s["workspaces"] if w["id"] == ws)["tab_ids"]

    assert tab_ids() == [t0, t1, t2]
    _req(
        f"{base}/api/workspaces/{ws}?t={T}",
        "PATCH",
        json.dumps({"tab_order": [t2, t0, t1]}).encode(),
    )
    assert tab_ids() == [t2, t0, t1]
    # Partial order + a foreign id: omitted tab is appended, foreign dropped.
    _req(
        f"{base}/api/workspaces/{ws}?t={T}",
        "PATCH",
        json.dumps({"tab_order": [t1, "ghost"]}).encode(),
    )
    assert tab_ids() == [t1, t2, t0]


def test_concurrent_tab_creation_does_not_race(server: LiveServer) -> None:
    """Regression: sync route handlers run in anyio's threadpool, so two
    ``POST /tabs`` calls can hit ``AppController.save`` while another is
    iterating ``state.tabs`` — used to raise ``RuntimeError: dictionary
    changed size during iteration``. The state lock now serializes them."""
    import concurrent.futures

    base = server.url
    st = _req(f"{base}/api/state?t={T}")
    ws = st["workspaces"][0]["id"]
    before = len(st["workspaces"][0]["tab_ids"])

    n = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        results = list(
            pool.map(
                lambda _i: _req(
                    f"{base}/api/workspaces/{ws}/tabs?t={T}",
                    "POST",
                    b"{}",
                ),
                range(n),
            )
        )

    assert len({r["id"] for r in results}) == n
    after = _req(f"{base}/api/state?t={T}")
    ws_view = next(w for w in after["workspaces"] if w["id"] == ws)
    assert len(ws_view["tab_ids"]) == before + n


def test_concurrent_spawns_of_one_tab_share_a_terminal(server: LiveServer) -> None:
    """``spawn_lock`` serializes spawns: two windows asking for the same
    tab's shell at once get one terminal, not two racing shells."""
    import concurrent.futures

    tab = _req(f"{server.url}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]
    url = f"{server.url}/api/tabs/{tab}/spawn?t={T}"
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        ids = set(
            pool.map(lambda _i: _req(url, "POST", b"{}")["terminal_id"], range(8))
        )
    assert len(ids) == 1


def test_unknown_ids_return_404(server: LiveServer) -> None:
    base = server.url
    for url, method in [
        (f"{base}/api/workspaces/ghost?t={T}", "PATCH"),
        (f"{base}/api/workspaces/ghost/tabs?t={T}", "POST"),
        (f"{base}/api/tabs/ghost?t={T}", "PATCH"),
        (f"{base}/api/tabs/ghost/spawn?t={T}", "POST"),
    ]:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _req(url, method, b"{}")
        assert exc.value.code == 404


def test_delete_last_workspace_recreates_one(server: LiveServer) -> None:
    base = server.url
    st = _req(f"{base}/api/state?t={T}")
    ws0 = st["workspaces"][0]["id"]
    _req(f"{base}/api/workspaces/{ws0}?t={T}", "DELETE", b"{}")
    st = _req(f"{base}/api/state?t={T}")
    assert len(st["workspaces"]) == 1
    assert st["workspaces"][0]["id"] != ws0
    assert st["active_workspace_id"] == st["workspaces"][0]["id"]


def test_delete_workspace_kills_its_terminals(server: LiveServer) -> None:
    base = server.url
    extra = _req(f"{base}/api/workspaces?t={T}", "POST", b"{}")["id"]
    st = _req(f"{base}/api/state?t={T}")
    tab = next(w for w in st["workspaces"] if w["id"] == extra)["tab_ids"][0]
    tid = _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")["terminal_id"]
    assert server.controller.terminals.get(tid) is not None
    _req(f"{base}/api/workspaces/{extra}?t={T}", "DELETE", b"{}")
    assert server.controller.terminals.get(tid) is None


# ----- data plane (PTY WebSocket) --------------------------------------


def test_ws_rejects_bad_token_and_unknown_terminal(server: LiveServer) -> None:
    wsbase = server.url.replace("http", "ws")

    async def expect_403(uri: str) -> None:
        # Closing before accept (bad token or unknown terminal) surfaces as
        # an HTTP 403 handshake rejection on the client.
        with pytest.raises(websockets.exceptions.InvalidStatus) as e:
            async with websockets.connect(uri):
                pass
        assert e.value.response.status_code == 403

    asyncio.run(expect_403(f"{wsbase}/pty/x?t=nope"))
    asyncio.run(expect_403(f"{wsbase}/pty/ghost?t={T}"))


def test_ws_pump_resize_and_exit(server: LiveServer) -> None:
    # Shell-agnostic: assert the bidirectional pump (we receive shell output,
    # the resize control frame is accepted, and exiting yields an exit frame).
    # Matching command output is too shell/line-editor dependent to assert on.
    base = server.url
    tab = _req(f"{base}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]
    tid = _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")["terminal_id"]
    url = base.replace("http", "ws") + f"/pty/{tid}?t={T}"

    async def scenario() -> None:
        async with websockets.connect(url) as c:

            async def run() -> None:
                saw_bytes = False
                acted = False
                while True:
                    m = await c.recv()  # plain recv; one outer wait_for guards
                    if isinstance(m, bytes):
                        saw_bytes = True
                        if not acted:
                            acted = True
                            await c.send(
                                json.dumps({"type": "resize", "cols": 100, "rows": 40}),
                            )
                            # Deterministic shutdown: deleting the tab closes
                            # the terminal server-side -> exit frame.
                            await asyncio.get_running_loop().run_in_executor(
                                None,
                                _req,
                                f"{base}/api/tabs/{tab}?t={T}",
                                "DELETE",
                                b"{}",
                            )
                    elif isinstance(m, str) and json.loads(m).get("type") == "exit":
                        assert saw_bytes
                        return

            await asyncio.wait_for(run(), timeout=15)

    asyncio.run(scenario())


def test_spawn_is_idempotent(server: LiveServer) -> None:
    base = server.url
    tab = _req(f"{base}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]
    a = _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")["terminal_id"]
    b = _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")["terminal_id"]
    assert a == b


# ----- controller helpers backed by a real terminal --------------------


def test_paste_inherit_and_active_terminal(server: LiveServer, tmp_path: Any) -> None:
    from pathlib import Path

    # On Windows the cwd comes from the shell (the test shell reports it;
    # the ``server`` fixture spawns it).
    base = server.url
    ctl = server.controller
    ws = ctl.state.workspaces[0]
    ctl.state.tabs[ws.active_tab_id].spawn_cwd = str(tmp_path)
    tab = ws.active_tab_id
    _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")

    term = ctl.active_terminal()
    assert term is not None
    # libproc reports the as-recorded cwd (``/tmp/...``) while ``tmp_path``
    # is the symlink-resolved form (``/private/tmp/...``) — compare resolved.
    target = str(Path(tmp_path).resolve())

    def resolved_cwd() -> str | None:
        value = term.cwd()
        return str(Path(value).resolve()) if value else None

    wait_until(lambda: resolved_cwd() == target)
    inherited = ctl.inherit_cwd(ws.id)
    assert inherited is not None
    assert str(Path(inherited).resolve()) == target

    written: list[bytes] = []
    term.write = written.append  # type: ignore[method-assign]
    ctl.paste_paths(["/a b/c.txt", "/d.txt"])
    ctl.paste_paths([])  # no-op, must not write
    assert written == [b"'/a b/c.txt' '/d.txt' "]


def test_index_requires_token_but_assets_are_public(server: LiveServer) -> None:
    """GET / embeds the session token in the HTML, so it must be gated —
    an unauthenticated fetch of / would hand out the token and defeat
    the auth entirely in web/remote mode. The content-hashed bundle
    stays public (the page needs it before any JS runs)."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server.url}/")  # noqa: S310
    assert exc.value.code == 403

    html = _get(f"{server.url}/?t={T}").decode()
    assert T in html  # the authed load still receives the injected token

    # /assets/* skips auth: a missing file 404s instead of 403ing.
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server.url}/assets/nope.js")  # noqa: S310
    assert exc.value.code == 404


def test_patch_workspace_ignores_foreign_active_tab(server: LiveServer) -> None:
    """A bogus/stale active_tab_id must not corrupt live state — it is
    silently ignored, matching the stale-client tolerance of reorders."""
    base = server.url
    ws = _req(f"{base}/api/state?t={T}")["workspaces"][0]
    good_tid = ws["active_tab_id"]
    assert good_tid is not None
    _req(
        f"{base}/api/workspaces/{ws['id']}?t={T}",
        method="PATCH",
        body=json.dumps({"active_tab_id": "not-a-real-tab"}).encode(),
    )
    after = _req(f"{base}/api/state?t={T}")["workspaces"][0]
    assert after["active_tab_id"] == good_tid


def test_malformed_numeric_bodies_return_400(server: LiveServer) -> None:
    base = server.url
    st = _req(f"{base}/api/state?t={T}")
    tid = st["workspaces"][0]["active_tab_id"]
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(
            f"{base}/api/tabs/{tid}/spawn?t={T}",
            method="POST",
            body=json.dumps({"cols": "wide"}).encode(),
        )
    assert exc.value.code == 400

    # A bad field rejects the whole PATCH: the valid sibling is not applied.
    before = st["ui"]["sidebar_width"]
    target = 300 if before != 300 else 320
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(
            f"{base}/api/ui?t={T}",
            method="PATCH",
            body=json.dumps({"sidebar_width": target, "font_size": "big"}).encode(),
        )
    assert exc.value.code == 400
    assert _req(f"{base}/api/state?t={T}")["ui"]["sidebar_width"] == before


def _status_of(url: str, method: str, body: bytes) -> tuple[int, Any]:
    try:
        return 200, _req(url, method=method, body=body)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.mark.parametrize(
    "body",
    [b"{not json", b"[]", b'"text"', b'{"cols": Infinity}', b'{"cols": null}'],
)
def test_malformed_bodies_are_json_400s(server: LiveServer, body: bytes) -> None:
    tid = _req(f"{server.url}/api/state?t={T}")["workspaces"][0]["active_tab_id"]
    code, payload = _status_of(f"{server.url}/api/tabs/{tid}/spawn?t={T}", "POST", body)
    assert code == 400
    assert payload["error"]


def test_patch_workspace_rejects_bad_types_before_changing_anything(
    server: LiveServer,
) -> None:
    ws = _req(f"{server.url}/api/state?t={T}")["workspaces"][0]
    url = f"{server.url}/api/workspaces/{ws['id']}?t={T}"
    for bad in ({"name": "renamed", "order": 5}, {"name": None}):
        code, payload = _status_of(url, "PATCH", json.dumps(bad).encode())
        assert code == 400, bad
        assert payload["error"].split()[0] in {"order", "name"}
    after = _req(f"{server.url}/api/state?t={T}")["workspaces"][0]
    assert after["name"] == ws["name"]


def test_out_of_range_terminal_size_is_clamped(server: LiveServer) -> None:
    """A size past ``struct winsize`` would kill the fork child before exec
    and wedge every later spawn; it's clamped at the boundary instead."""
    st = _req(f"{server.url}/api/state?t={T}")
    tid = st["workspaces"][0]["active_tab_id"]
    spawned = _req(
        f"{server.url}/api/tabs/{tid}/spawn?t={T}",
        method="POST",
        body=json.dumps({"cols": 70000, "rows": -5}).encode(),
    )
    assert server.controller.terminals.get(spawned["terminal_id"]) is not None
    # ...and the next spawn still works.
    ws = _req(f"{server.url}/api/workspaces?t={T}", method="POST", body=b"")
    st = _req(f"{server.url}/api/state?t={T}")
    tid2 = next(w for w in st["workspaces"] if w["id"] == ws["id"])["active_tab_id"]
    assert _req(
        f"{server.url}/api/tabs/{tid2}/spawn?t={T}",
        method="POST",
        body=b'{"cols": 80, "rows": 24}',
    )["terminal_id"]


def test_connect_info_reports_bind_and_stability(server: LiveServer) -> None:
    """The overlay needs to know whether a tunnel is required and whether
    the URL outlives the run; the test server is loopback + per-session."""
    info = _req(f"{server.url}/api/connect-info?t={T}")
    assert info["loopback_only"] is True
    assert info["bind_host"] == "127.0.0.1"
    assert info["stable_url"] is False
    assert info["hostname"]  # always known, unlike the LAN address
    # Port is None here: the fixture binds uvicorn itself rather than
    # going through main(), which is what records it.
    assert info["port"] is None
    assert set(info) == {
        "hostname",
        "lan_ip",
        "bind_host",
        "port",
        "loopback_only",
        "stable_url",
    }


def test_connect_info_follows_the_bind_it_was_given(server: LiveServer) -> None:
    """A server bound beyond loopback reports that a client can connect
    straight to it — the branch that skips the SSH recipe."""
    app_state = server.app.state
    app_state.bind_host = "0.0.0.0"  # noqa: S104 — the case under test
    app_state.bind_port = 8443
    app_state.token_persistent = True
    try:
        info = _req(f"{server.url}/api/connect-info?t={T}")
        assert info["loopback_only"] is False
        assert info["stable_url"] is True
        # The server's own port, not the one this client connected to.
        assert info["port"] == 8443
    finally:
        app_state.bind_host = "127.0.0.1"
        app_state.bind_port = None
        app_state.token_persistent = False


# ----- several clients on one terminal ------------------------------------


async def _until(ws: Any, accept: Any, timeout: float = 8.0) -> Any:
    """Receive frames until ``accept(frame)`` holds; return that frame."""

    async def go() -> Any:
        while True:
            frame = await ws.recv()
            if accept(frame):
                return frame

    return await asyncio.wait_for(go(), timeout)


def _owner_frame(value: bool) -> Any:
    return lambda m: (
        isinstance(m, str) and json.loads(m) == {"type": "owner", "owner": value}
    )


async def _output_until(ws: Any, marker: bytes, timeout: float = 8.0) -> bytes:
    """Collect PTY output bytes until ``marker`` shows up; return them all."""
    buf = b""

    async def go() -> bytes:
        nonlocal buf
        while marker not in buf:
            frame = await ws.recv()
            if isinstance(frame, bytes):
                buf += frame
        return buf

    return await asyncio.wait_for(go(), timeout)


def test_the_client_in_use_owns_the_terminal_size_and_input(
    server: LiveServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A desktop window and a --connect window on the same terminal (the
    garbled-screen bug): the watcher's size never reaches the PTY, its
    emulator's stray answers never reach the shell, a claim moves both, and
    the owner leaving hands everything back."""
    base = server.url
    tab = _req(f"{base}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]
    tid = _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")["terminal_id"]
    url = base.replace("http", "ws") + f"/pty/{tid}?t={T}"
    term = server.controller.terminals.get(tid)
    assert term is not None

    # Record what reaches the backend (portable: no ConPTY size getter).
    sizes: list[tuple[int, int]] = [(80, 24)]
    real_resize = term._pty.resize

    def recording_resize(cols: int, rows: int) -> None:
        sizes.append((cols, rows))
        real_resize(cols, rows)

    monkeypatch.setattr(term._pty, "resize", recording_resize)

    def pty_size() -> tuple[int, int]:  # (cols, rows) as last set on the PTY
        return sizes[-1]

    async def size_becomes(expected: tuple[int, int]) -> None:
        for _ in range(250):
            if pty_size() == expected:
                return
            await asyncio.sleep(0.02)
        msg = f"PTY stayed {pty_size()}, expected {expected}"
        raise AssertionError(msg)

    async def scenario() -> None:
        async with websockets.connect(url) as desk:
            await _until(desk, _owner_frame(True))  # first to attach owns
            await desk.send(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
            await size_becomes((100, 30))

            async with websockets.connect(url) as laptop:
                await _until(laptop, _owner_frame(False))  # attaches as watcher
                # The watcher's size and bytes (like an emulator's answer to
                # a cursor-position query) must not touch the terminal.
                await laptop.send(
                    json.dumps({"type": "resize", "cols": 60, "rows": 20})
                )
                await laptop.send(b"echo LAPTOP_EARLY\r")
                await asyncio.sleep(0.5)
                await desk.send(b"echo DESK_SEES\r")
                seen = await _output_until(desk, b"DESK_SEES")
                assert b"LAPTOP_EARLY" not in seen
                assert pty_size() == (100, 30)

                # The user moves to the laptop: one claim switches the
                # owner, notifies both sides, and re-sizes the PTY.
                await laptop.send(json.dumps({"type": "claim"}))
                await _until(laptop, _owner_frame(True))
                await _until(desk, _owner_frame(False))
                await size_becomes((60, 20))
                await laptop.send(b"echo LAPTOP_OWNS\r")
                await _output_until(laptop, b"LAPTOP_OWNS")

            # The laptop disconnects: the desktop owns it again, at its size.
            await _until(desk, _owner_frame(True))
            await size_becomes((100, 30))

    asyncio.run(scenario())


def test_typing_in_a_terminal_marks_its_workspace_as_last_used(
    server: LiveServer,
) -> None:
    """End to end for "Sort by Recent Activity": a keystroke over the PTY
    websocket shows up as the workspace's ``last_used_at`` in the state."""
    base = server.url
    ws0 = _req(f"{base}/api/state?t={T}")["workspaces"][0]
    assert ws0["last_used_at"] is None
    tid = _req(f"{base}/api/tabs/{ws0['tab_ids'][0]}/spawn?t={T}", "POST", b"{}")[
        "terminal_id"
    ]
    url = base.replace("http", "ws") + f"/pty/{tid}?t={T}"
    before = time.time()

    async def scenario() -> None:
        async with websockets.connect(url) as client:
            await _until(client, _owner_frame(True))
            await client.send(b" ")
            for _ in range(250):
                used = _req(f"{base}/api/state?t={T}")["workspaces"][0]["last_used_at"]
                if used is not None:
                    assert used >= before
                    return
                await asyncio.sleep(0.02)
            msg = "last_used_at was never set"
            raise AssertionError(msg)

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX /bin/sh")
def test_exited_shell_is_freed(server: LiveServer, monkeypatch) -> None:
    """When the shell exits, its terminal (PTY, backlog, busy tracking)
    leaves the registry; the tab can start a fresh one."""
    monkeypatch.setattr(
        "terminux.server.controller.default_shell", lambda: ["/bin/sh", "-c", "exit 0"]
    )
    ctl = server.controller
    tab = _req(f"{server.url}/api/state?t={T}")["workspaces"][0]["tab_ids"][0]
    url = f"{server.url}/api/tabs/{tab}/spawn?t={T}"
    tid = _req(url, "POST", b"{}")["terminal_id"]
    assert wait_until(lambda: ctl.terminals.get(tid) is None)
    assert ctl.state.tabs[tab].terminal_id is None
    assert _req(url, "POST", b"{}")["terminal_id"] != tid
