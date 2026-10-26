# HTTP & WebSocket API

The frontend drives the backend over a JSON control plane (`/api/...`) and one WebSocket per terminal (`/pty/{terminal_id}`). The same API serves the desktop window, browser mode, and `--connect` clients, so everything the UI does can be done with `curl` and a WebSocket client.

!!! warning "Internal API"
    This API ships in lockstep with its only client, the bundled frontend. It is documented for debugging, scripting against your own instance, and contributing. It comes with no stability promise: any release may change it.

## Authentication

Every request and WebSocket must include the session token as a query parameter: `?t=<token>`. The token is printed in the startup URL (`http://127.0.0.1:<port>/?t=abc-def-ghi`); `--server` mode persists it in `server.token`. Requests without a valid token get `403 {"error": "forbidden"}`. Only the static asset bundle under `/assets/` is served without a token.

The server rate-limits non-loopback clients. After 10 bad tokens from one IP, it locks that IP out for 60 s.

## Control plane

Errors come back as JSON (`{"error": "..."}`) with 400/403/404/409/413 as appropriate; a 404 names what is missing (`no tab '…'`). Successful mutations return `{"ok": true}` unless noted, and creations answer 201.

| Method & path | Body | Returns |
| --- | --- | --- |
| `GET /api/state` | *none* | Full state snapshot: workspaces (with status and active seconds), tabs, UI prefs |
| `GET /api/connect-info` | *none* | How to reach this server from elsewhere: `hostname`, `lan_ip`, `public_host` (from `--public-host`, else null), `bind_host`, `port`, `loopback_only`, `stable_url` |
| `POST /api/workspaces` | *none* | 201 `{"id": ...}`; creates a workspace with one tab and activates it |
| `PATCH /api/workspaces/{id}` | any of `name` (pins; blank goes back to the cwd), `active: true`, `active_tab_id`, `order` (workspace ids), `tab_order` (tab ids) | `{"ok": true}` |
| `DELETE /api/workspaces/{id}` | *none* | Kills its terminals, drops its scrollback; at least one workspace always remains |
| `POST /api/workspaces/{id}/tabs` | *none* | 201 `{"id": ...}`; the new tab inherits the active shell's directory |
| `PATCH /api/tabs/{id}` | `title` (pins; blank unpins) or `osc_title` (tracks unless pinned) | `{"ok": true}` |
| `DELETE /api/tabs/{id}` | *none* | Kills the shell and the saved scrollback; 409 for a workspace's last tab (close the workspace instead) |
| `POST /api/tabs/{id}/spawn` | `{"cols": N, "rows": N}` | `{"terminal_id": ...}`; idempotent while the shell lives |
| `GET /api/tabs/{id}/scrollback` | *none* | The saved buffer: a one-line JSON header (`{"v":2,"cols":…,"rows":…}`) then raw ANSI |
| `PUT /api/tabs/{id}/scrollback` | the buffer in the same envelope | 413 above 4 MB |
| `DELETE /api/tabs/{id}/scrollback` | *none* | Drops the saved buffer |
| `PATCH /api/ui` | any UI pref: `font_size`, `sidebar_width`, `sidebar_collapsed`, `copy_on_select`, `scrollback_persist`, `win_*` | Values are validated and clamped; a malformed field rejects the whole PATCH with 400 |
| `POST /api/open-url` | `{"url": ...}` | Opens in the OS default app; only `http`, `https`, `mailto` |
| `POST /api/paste-paths` | `{"paths": [...]}` | Types shell-quoted paths into the active terminal |
| `POST /api/activity/reset` | *none* | Clears the per-workspace activity counters |

A minimal session from the shell looks like this:

```sh
BASE="http://127.0.0.1:PORT"; T="?t=abc-def-ghi"
curl "$BASE/api/state$T" | jq '.workspaces[].name'
TAB=$(curl -s "$BASE/api/state$T" | jq -r '.workspaces[0].active_tab_id')
curl -X POST "$BASE/api/tabs/$TAB/spawn$T" -d '{"cols":120,"rows":30}'
```

## Data plane: `WS /pty/{terminal_id}`

Connect with the token (`/pty/<terminal_id>?t=<token>`) after obtaining a `terminal_id` from `spawn`. The protocol:

- **Binary frames, both directions**: raw PTY bytes. Client to server is keyboard input; server to client is terminal output.
- **Text frames are JSON control messages.** The client sends `{"type": "resize", "cols": N, "rows": N}` to report its size and `{"type": "claim"}` to take ownership (below). The server sends `{"type": "owner", "owner": true|false}` on attach and whenever ownership changes, `{"type": "exit", "code": N}` when the shell ends, `{"type": "dropped"}` once if a slow consumer's backlog had to be discarded, and `{"type": "replayed"}` once, where the replayed backlog ends. Until then, a client should send nothing. Its emulator is answering queries from old output (cursor position, colors) that another client already answered, so those answers would land in the shell as typed input. The terminal's first client gets the marker *before* the backlog: no client has answered a new shell's startup queries yet. Some shells (fish) wait for those answers.

On connect the server replays its retained output backlog (up to 512 KB), which is what lets a reconnecting client repaint the screen. A terminal accepts **multiple simultaneous subscribers**, and every one of them receives all output.

**Ownership.** A PTY has one size, so one subscriber at a time owns the terminal. The first to attach owns it. A `resize` from the owner resizes the PTY; a `resize` from anyone else is only recorded. A `claim` makes the sender the owner and resizes the PTY to its recorded size. Binary input from a non-owner is dropped: in practice it is the emulator's automatic answers to the program's queries (cursor position, device attributes), which describe the wrong screen. A client must therefore send `claim` before any real input; the bundled frontend does so on keystrokes, clicks, pastes, window focus, and tab switches. When the owner disconnects, the most recently attached remaining subscriber takes over.

A bad token or an unknown terminal id is refused during the handshake, so the client gets an HTTP 403 before any WebSocket opens. A terminal whose shell has exited is gone too: ask `/spawn` for a fresh one.
