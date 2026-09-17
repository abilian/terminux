# HTTP & WebSocket API

The frontend drives the backend over a JSON control plane (`/api/...`) and one WebSocket per terminal (`/pty/{terminal_id}`). The same API serves the desktop window, browser mode, and `--connect` clients, so everything the UI does can be done with `curl` and a WebSocket client.

!!! warning "Internal API"
    This API ships in lockstep with its only client, the bundled frontend. It is documented for debugging, scripting against your own instance, and contributing; it carries no stability promise, and any release may change it.

## Authentication

Every request and WebSocket carries the session token as a query parameter: `?t=<token>`. The token is printed in the startup URL (`http://127.0.0.1:<port>/?t=abc-def-ghi`); `--server` mode persists it in `server.token`. Requests without a valid token get `403 {"error": "forbidden"}`. Only the static asset bundle under `/assets/` is served without a token.

Non-loopback clients are rate-limited: 10 bad tokens from one IP lock that IP out for 60 s.

## Control plane

Errors come back as JSON (`{"error": "..."}`) with 400/403/404/413 as appropriate; successful mutations return `{"ok": true}` unless noted.

| Method & path | Body | Returns |
| --- | --- | --- |
| `GET /api/state` | *none* | Full state snapshot: workspaces (with status and active seconds), tabs, UI prefs |
| `POST /api/workspaces` | *none* | `{"id": ...}`; creates a workspace with one tab and activates it |
| `PATCH /api/workspaces/{id}` | any of `name`, `active: true`, `active_tab_id`, `order` (workspace ids), `tab_order` (tab ids) | `{"ok": true}` |
| `DELETE /api/workspaces/{id}` | *none* | Kills its terminals, drops its scrollback; at least one workspace always remains |
| `POST /api/workspaces/{id}/tabs` | *none* | `{"id": ...}`; the new tab inherits the active shell's directory |
| `PATCH /api/tabs/{id}` | `title` (pins) or `osc_title` (tracks unless pinned) | `{"ok": true}` |
| `DELETE /api/tabs/{id}` | *none* | Kills the shell and the saved scrollback |
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
- **Text frames are JSON control messages.** The client sends `{"type": "resize", "cols": N, "rows": N}`. The server sends `{"type": "exit", "code": N}` when the shell ends, and `{"type": "dropped"}` once if a slow consumer's backlog had to be discarded.

On connect the server replays its retained output backlog (up to 512 KB), which is what lets a reconnecting client repaint the screen. A terminal accepts **multiple simultaneous subscribers**: two windows attached to the same terminal both see all output and can both type, like `tmux attach` from two places.

The close codes are `4403` (bad token) and `4404` (unknown terminal id).
