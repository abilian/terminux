# Technical Specification: terminux v1

**Status:** Historical v1 technical design. Implementation has shipped and evolved beyond this baseline; see [`CHANGES.md`](../CHANGES.md) for what landed, [`docs/src/developers/architecture.md`](../docs/src/developers/architecture.md) for the current shape, and [`04-backlog.md`](04-backlog.md) for what's still ahead. This doc is kept as the record of original architectural decisions.

Implements [`01-functional-spec.md`](01-functional-spec.md). The architecture is a thin web UI rendering xterm.js, separated from a backend process that owns the PTY and streams raw bytes. The backend is **Python** and the desktop shell is **pywebview**.

The decision of record is that the webview talks to Python over a **loopback HTTP + WebSocket server** hosted in the Python process; pywebview is only a window pointing at that local URL. This was chosen over the pure pywebview `js_api` bridge because it makes the later goals (web mode, client/server) near-free, where the bridge would have meant a rewrite.

## 1. Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python ≥ 3.12 | Project requirement; matches `pyproject.toml` (`terminux`). |
| Desktop shell | **pywebview** | Mature, simple; just hosts a window at a local URL. No Rust. |
| Backend server | **Starlette + uvicorn** (ASGI) | Lean: static files + WebSocket + (future) JSON HTTP. Web mode means serving the page to a browser; client/server means binding beyond loopback. |
| PTY (Unix) | **`ptyprocess`** | Proven in production (pexpect lineage): spawn, winsize, signals. |
| PTY (Windows) | **`pywinpty`** (ConPTY) | Staged after Unix (see §10). |
| Terminal UI | **xterm.js** + WebGL/canvas addon, fit addon | Fast, well-supported, widely used. |
| App-data paths | **`platformdirs`** | Correct per-OS config/data dirs. |
| Frontend build | Vanilla TS + **Vite** (or plain ESM, no build) | UI is tiny in v1; keep build minimal. Decide in impl. |
| Tooling | uv, ruff, mypy/ty/pyrefly, pytest (existing) | Already configured in repo. |

Runtime Python deps: `pywebview`, `starlette`, `uvicorn`, `ptyprocess`, `platformdirs`, and `websockets` (the WebSocket implementation uvicorn runs Starlette's WS endpoints on). Windows adds `pywinpty`.

## 2. Process & threading model

Single OS process in v1, two cooperating execution contexts:

```
main() ──┬─ start backend (uvicorn) in a daemon thread, its own asyncio loop
         │     bind 127.0.0.1:<ephemeral>, generate session token
         │     wait until server is listening (Event)
         │
         └─ webview.create_window(url=f"http://127.0.0.1:{port}/?t={token}")
            webview.start()            # blocks on the GUI loop (main thread)
                                       # on window close → signal shutdown
```

- **Main thread:** pywebview GUI loop. Required (GUI toolkits demand the main thread).
- **Backend thread:** the asyncio event loop running uvicorn/Starlette. Owns all PTYs and all state. The webview never touches the OS directly: every privileged action is an HTTP/WS message, so the webview stays sandboxed.
- **PTY I/O:** on Unix the master fd is registered with the backend loop via `loop.add_reader`; reads are drained into a per-terminal buffer and flushed on a ~4–8 ms timer to the terminal's WebSocket as binary frames (batched flushes: no per-byte context switch, no JSON/base64 on the hot path). No thread-per-PTY on Unix.
- **Shutdown:** window close → set a shutdown event → backend gracefully terminates all child shells (SIGHUP→SIGTERM→SIGKILL escalation with a short grace), stops uvicorn, process exits. No zombies (functional spec §10).

## 3. Transport / protocol

The transport has two planes, control and data:

### 3.1 Control plane: HTTP + JSON (request/response)

Used for structure and persistence (cheap, low-frequency). All endpoints sit behind a token check (§6):

- `GET /` → the single-page UI (HTML/JS/xterm.js).
- `GET /state` → full persisted app state (workspaces, tabs, ordering, active ids, UI prefs).
- `POST /workspaces` / `PATCH /workspaces/{id}` / `DELETE /workspaces/{id}` → create / rename+reorder / close.
- `POST /workspaces/{id}/tabs` / `PATCH /tabs/{id}` / `DELETE /tabs/{id}` → tab CRUD.
- `POST /tabs/{id}/spawn` → ensure a live terminal exists for the tab; returns a `terminal_id`.

(These can also be modeled as JSON-RPC over one control WebSocket later; HTTP is simplest for v1 and most web-mode/client-server friendly.)

### 3.2 Data plane: one WebSocket per live terminal

`WS /pty/{terminal_id}?t=<token>`:

- **Binary frame, server→client:** raw PTY output bytes (batched).
- **Binary frame, client→server:** raw keyboard/paste bytes → written to the PTY master.
- **Text frame (JSON), client→server:** control: `{"type":"resize","cols":C,"rows":R}`.
- **Text frame (JSON), server→client:** lifecycle: `{"type":"exit","code":N}`, `{"type":"dropped"}` (backpressure notice), `{"type":"title","text":"…"}` (from OSC 0/2 if parsed server-side; OSC parsing may instead live in xterm.js, to be decided in impl).

Rationale for per-terminal WS: isolates backpressure per terminal, keeps framing trivial (binary = bytes, text = control), and maps 1:1 to "open the same WS to a remote host" for future client/server.

### 3.3 Backpressure

Per-terminal output buffer has a cap (e.g., 4 MiB). On overflow: drop the buffered output, send one `{"type":"dropped"}` notice, log at WARN. UI shows a `[output dropped]` marker. Never let a runaway process freeze the UI or grow memory unbounded (functional spec §10).

## 4. Backend module layout

Under `src/terminux/` (repo uses a `src/` layout; `Makefile` covers `--cov=terminux`):

```
src/terminux/
  __init__.py
  __main__.py            # `python -m terminux` → main()
  app.py                 # main(): start server thread, launch pywebview, wire shutdown
  server/
    asgi.py              # Starlette app: routes, static, lifespan
    control.py           # HTTP control-plane handlers (state, workspaces, tabs)
    pty_ws.py            # WebSocket endpoint: per-terminal byte pump + control
    auth.py              # session-token check (HTTP + WS)
  core/
    model.py             # Workspace, Tab dataclasses; in-memory AppState; status logic
    persistence.py       # atomic JSON load/save, debounced autosave, schema + migration
    terminal.py          # Terminal: owns a PTY child; read/write/resize/kill; backpressure
    pty_backend.py       # PtyBackend protocol; UnixPty (ptyprocess); WindowsPty (pywinpty)
    shellprobe.py        # default shell + cwd resolution per OS
  web/                   # frontend (served by server/asgi.py)
    index.html
    main.ts              # xterm.js wiring, WS client, tab/sidebar rendering, shortcuts
    ...                  # (build via Vite or shipped as static ESM — TBD in impl)
```

Test tiers already exist: `tests/a_unit`, `tests/b_integration`, `tests/c_e2e`.

## 5. Data model & persistence

In-memory authoritative state lives in the backend (`core/model.py`):

```python
@dataclass
class Tab:
    id: str            # uuid4
    title: str
    user_set_title: bool = False
    # transient (not persisted): live Terminal | None, has_unseen_output: bool

@dataclass
class Workspace:
    id: str
    name: str
    tab_ids: list[str]          # order
    active_tab_id: str | None

@dataclass
class AppState:
    workspaces: list[Workspace] # order
    tabs: dict[str, Tab]
    active_workspace_id: str | None
    ui: UiPrefs                 # window geometry, sidebar width/collapsed, font zoom
```

**Persistence file:** `platformdirs.user_data_dir("terminux")/state.json`, schema-versioned (`{"version": 1, ...}`). Writes are atomic (write temp file, `os.replace`). Autosave is debounced (~500 ms after the last mutating control-plane action) plus a save on graceful shutdown. Live terminals/scrollback are **not** persisted (functional spec §7); a restored tab spawns a fresh shell. Corrupt/missing file → log + start from a one-workspace/one-tab default; never crash.

**Forward-compatibility for splits:** `Tab` is the persistence unit now. To allow tmux/zellij-style panes later without a migration headache, reserve an optional `panes` field shape in the schema design (a recursive `{leaf|split}` node) even though v1 only ever has the implicit single pane. Document it as reserved; don't implement it.

## 6. Security

A loopback HTTP server is reachable by *any* local process or browser tab, so the design does the following:

- Bind strictly to `127.0.0.1` on an OS-assigned ephemeral port.
- Generate a random **session token** at startup. (It shipped as a 9-letter code, about 43 bits, so it can be read aloud; per-IP lockout after repeated failures guards against brute force. See `server/auth.py`.) The webview URL includes it (`/?t=…`); every HTTP request and WS upgrade must present it (header or query). Reject otherwise. This stops other local apps/pages from driving terminals or reading output.
- Restrictive CSP on the served page; no remote origins; WS only to same origin.
- No network egress; nothing is sent off-machine.
- (Client/server mode later will replace the token with a real auth story before binding beyond loopback. This is explicitly a future concern, called out so it isn't forgotten.)

## 7. Key lifecycles

**Startup:** parse args → load state (or default) → start backend thread (bind, token, mark ready) → create pywebview window at local URL → `webview.start()`. UI fetches `/state`, renders sidebar/tabs, then for the active workspace's tabs calls `/tabs/{id}/spawn` and opens a `WS /pty/{tid}`. Non-active workspaces' shells spawn lazily on first selection (functional spec §7).

**Spawn terminal:** `POST /tabs/{id}/spawn` → `Terminal` created → `PtyBackend.spawn(shell, cwd, env, cols, rows)` → master fd registered with the loop → returns `terminal_id` → UI opens the WS.

**I/O:** loop reader drains master fd → per-terminal buffer → flush timer sends a binary WS frame. Client keystrokes → binary WS frame → `os.write(master_fd, data)`. A `resize` JSON message becomes `TIOCSWINSZ` on Unix and a ConPTY resize on Windows.

**Tab/workspace close:** control-plane DELETE → terminate child (SIGHUP→SIGTERM→SIGKILL grace) → close WS → update state → debounced save. Workspace close confirmation is enforced in the UI; backend just executes.

**Shell exits on its own:** reader sees EOF / `waitpid` → send `{"type":"exit","code":N}` → UI shows the exited-tab affordance; the `Tab` persists, the `Terminal` is cleared.

**Shutdown:** window close → shutdown event → terminate all children with grace → final state save → uvicorn stop → exit.

## 8. Concurrency & correctness rules

- All `AppState` mutation happens on the backend asyncio loop (single-threaded), so state needs no locks; the GUI thread only sends messages.
- One serialization point for PTY spawn (an asyncio lock) to avoid pipe-stall races under rapid tab creation.
- Bounded per-terminal buffers; flush coalescing; drop-with-notice on overflow.
- Idempotent spawn: `POST /tabs/{id}/spawn` returns the existing `terminal_id` if already live (handles UI reconnects).
- WS reconnect: if the UI WS drops but the PTY lives, the UI can reopen `WS /pty/{tid}`; backend resumes streaming from "now" (no replay in v1, consistent with no-scrollback-persistence).

## 9. Error handling

- Bad/missing persisted state → default state + WARN log; never crash.
- PTY spawn failure (bad shell, exec error) → control-plane returns an error; UI shows it in the tab; tab still exists.
- Port bind failure → retry with a new ephemeral port a few times, then fail fast with a clear message.
- Backend thread crash → surface a fatal error window and exit non-zero (don't leave a half-dead UI).
- Logging via stdlib `logging` to the platform log/data dir; levels configurable by env var.

## 10. Cross-platform plan

- **macOS:** primary target. pywebview uses the WKWebView backend; Unix PTY via `ptyprocess`.
- **Linux:** same Unix PTY path; pywebview GTK/Qt backend (document the chosen backend + its system deps).
- **Windows:** **staged.** Needs `pywinpty` (ConPTY) behind the `PtyBackend` protocol, ConPTY resize, and process-tree kill (a Job Object). See [`06-windows-port.md`](06-windows-port.md). Default shell probe: `pwsh` → `powershell` → `cmd`. Land Unix first; Windows behind the same interface so it's additive, not a rewrite.

`core/pty_backend.py` defines a `PtyBackend` Protocol (`spawn`, `read`-source/fd, `write`, `resize`, `kill`, `wait`) with `UnixPty` and `WindowsPty` implementations; the rest of the code is OS-agnostic.

## 11. Testing strategy

Map to the existing tiers:

- **`tests/a_unit`** covers pure logic, no OS: `AppState` transitions (create/rename/reorder/close, status derivation, last-workspace invariant), persistence (atomic write, schema version, corrupt-file fallback), protocol framing/auth-token checks.
- **`tests/b_integration`** uses a real PTY + real server, no GUI: spawn a shell via `UnixPty`, echo round-trip, resize takes effect (`stty size`), backpressure drop path, EOF→exit event; Starlette `TestClient` for HTTP control plane and a WS client for the byte pump.
- **`tests/c_e2e`**: because the UI is a normal web page served over HTTP, drive it with Playwright pointed at the live local URL **without** launching pywebview (a major payoff of the chosen transport: e2e doesn't need the native shell). Cover: create/switch/close workspace and tab, type+see echo, background-tab keeps streaming, restart restores structure (fresh shells), graceful shutdown leaves no child processes.

CI runs Unix tiers; Windows e2e added when the Windows PTY lands.

## 12. How this enables the "later" goals (no rewrite)

- **Web mode:** the UI is already an HTTP-served page + WS. Add a flag to bind the server to a chosen interface and serve the page to a normal browser; replace the loopback token with real auth (§6 note). No UI rewrite.
- **Client/server mode:** the backend already *is* a server owning the PTYs. Detach it from pywebview (run headless), let a UI connect over the same HTTP/WS protocol; terminals keep running across UI restarts because the server process outlives the window. Persistence schema already separates structure from live processes.
- **Split panes:** UI introduces a per-tab pane tree; each leaf is just another `WS /pty/{tid}`. Persistence schema reserved the shape (§5). Backend per-terminal model is unchanged: a tab holds N terminals where it held 1.

Each future item is additive along an interface that already exists, which is the whole reason for choosing the local-server transport over the `js_api` bridge.

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| pywebview backend variance across OSes (GTK/Qt/WKWebView/EdgeWebView2) quirks | Pin/document the backend per OS; keep UI to mainstream web APIs; e2e via Playwright catches regressions independent of pywebview. |
| Local server reachable by other local processes | Loopback-only + per-session token + CSP (§6). |
| High-throughput output freezing UI | Server-side batched flush + bounded buffer + drop-with-notice (§3.3). |
| Asyncio + GUI-thread interplay deadlocks | Strict rule: GUI thread sends messages only; all state/PTY work on the backend loop (§8). |
| Windows PTY complexity creeping into core | `PtyBackend` Protocol isolates it; Unix ships first (§10). |
| Frontend build complexity | Keep v1 UI tiny; prefer no-build static ESM or minimal Vite; decide early, don't over-engineer. |

## 14. Open questions (resolve during implementation)

1. Frontend build: plain static ESM vs. Vite. Pick the lightest that works.
2. OSC 0/2 title parsing: in xterm.js (client) vs. server-side. Likely client.
3. pywebview GUI backend per OS (esp. Linux GTK vs. Qt) and its packaging implications.
4. Packaging/distribution (PyInstaller / briefcase / uv tool) is out of v1 spec scope; note it's unaddressed.
5. Eager-vs-lazy shell spawn tuning on restore (also a functional-spec open question).
6. Exact backpressure thresholds and flush interval (start from 4 MiB / ~4 ms, tune).
