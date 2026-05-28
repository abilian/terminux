"""Integration tests exercising every HTTP/WebSocket handler."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import websockets

from terminux.server.auth import SESSION_TOKEN

if TYPE_CHECKING:
    from tests.b_integration.conftest import LiveServer

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


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/state", "GET"),
        ("/api/workspaces", "POST"),
        ("/api/workspaces/x", "PATCH"),
        ("/api/workspaces/x", "DELETE"),
        ("/api/workspaces/x/tabs", "POST"),
        ("/api/tabs/x", "PATCH"),
        ("/api/tabs/x", "DELETE"),
        ("/api/tabs/x/spawn", "POST"),
    ],
)
def test_endpoints_require_token(server: LiveServer, path: str, method: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _req(f"{server.url}{path}", method=method, body=b"{}")
    assert exc.value.code == 403


# ----- static ----------------------------------------------------------


def test_index_serves_built_bundle_with_token(server: LiveServer) -> None:
    index = _get(f"{server.url}/").decode()
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
    with urllib.request.urlopen(f"{server.url}/") as r:  # noqa: S310
        headers = r.headers
    csp = headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'none'" in csp
    assert "connect-src 'self'" in csp
    # Regression guard: pywebview's evaluate_js needs 'unsafe-eval'.
    assert "'unsafe-eval'" in csp
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"


# ----- workspace / tab control plane -----------------------------------


def test_workspace_and_tab_lifecycle(server: LiveServer) -> None:
    base = server.url
    st = _req(f"{base}/api/state?t={T}")
    assert len(st["workspaces"]) == 1
    ws0 = st["workspaces"][0]["id"]

    new = _req(f"{base}/api/workspaces?t={T}", "POST", b"{}")
    ws1 = new["id"]
    st = _req(f"{base}/api/state?t={T}")
    assert st["active_workspace_id"] == ws1

    # rename + reorder + activate + active_tab_id
    _req(
        f"{base}/api/workspaces/{ws1}?t={T}",
        "PATCH",
        json.dumps({"name": "renamed", "active": True}).encode(),
    )
    _req(
        f"{base}/api/workspaces/{ws0}?t={T}",
        "PATCH",
        json.dumps({"order": [ws1, ws0]}).encode(),
    )
    st = _req(f"{base}/api/state?t={T}")
    names = {w["id"]: w["name"] for w in st["workspaces"]}
    assert names[ws1] == "renamed"
    assert [w["id"] for w in st["workspaces"]] == [ws1, ws0]

    # tab create + rename + set active_tab_id (valid + None) + delete
    tab = _req(f"{base}/api/workspaces/{ws1}/tabs?t={T}", "POST", b"{}")["id"]
    _req(
        f"{base}/api/tabs/{tab}?t={T}",
        "PATCH",
        json.dumps({"title": "logs"}).encode(),
    )
    _req(
        f"{base}/api/workspaces/{ws1}?t={T}",
        "PATCH",
        json.dumps({"active_tab_id": tab}).encode(),
    )
    _req(
        f"{base}/api/workspaces/{ws1}?t={T}",
        "PATCH",
        json.dumps({"active_tab_id": None}).encode(),
    )
    st = _req(f"{base}/api/state?t={T}")
    assert st["tabs"][tab]["title"] == "logs"
    _req(f"{base}/api/tabs/{tab}?t={T}", "DELETE", b"{}")
    assert tab not in _req(f"{base}/api/state?t={T}")["tabs"]


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
    deadline = time.time() + 6
    while time.time() < deadline and term.cwd() != str(target):
        time.sleep(0.1)

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

    # Patch the opener so the test never actually spawns `open`.
    from terminux.server import asgi

    calls: list[str] = []
    monkey = asgi.open_url_in_default_app
    asgi.open_url_in_default_app = lambda u: (calls.append(u), True)[1]  # type: ignore[assignment]
    try:
        _req(
            f"{base}/api/open-url?t={T}",
            "POST",
            json.dumps({"url": "https://example.com/path?x=1"}).encode(),
        )
        assert calls == ["https://example.com/path?x=1"]
    finally:
        asgi.open_url_in_default_app = monkey  # type: ignore[assignment]


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
    base = server.url
    ctl = server.controller
    ws = ctl.state.workspaces[0]
    ctl.state.tabs[ws.active_tab_id].spawn_cwd = str(tmp_path)
    tab = ws.active_tab_id
    _req(f"{base}/api/tabs/{tab}/spawn?t={T}", "POST", b"{}")

    term = ctl.active_terminal()
    assert term is not None
    deadline = time.time() + 6
    while time.time() < deadline and term.cwd() != str(tmp_path):
        time.sleep(0.1)
    assert ctl.inherit_cwd(ws.id) == str(tmp_path)

    written: list[bytes] = []
    term.write = written.append  # type: ignore[method-assign]
    ctl.paste_paths(["/a b/c.txt", "/d.txt"])
    ctl.paste_paths([])  # no-op, must not write
    assert written == [b"'/a b/c.txt' '/d.txt' "]
