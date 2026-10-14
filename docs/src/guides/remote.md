# Remote access

Run terminux on one machine (a headless server, a desktop tower, a NUC,
a Raspberry Pi) and connect from another (your laptop). Your shells live
on the server: long-running builds keep going while you switch
networks, sleep your laptop, or move to a different room.

The architecture is intentionally thin:

- **Server** (`--server`) is the existing Starlette/uvicorn backend with a
  persistent auth token and a connect-banner. The full frontend
  (xterm.js, sidebar, persistence) is served from the same process.
- **Client** (`--connect URL`) is a native pywebview window pointed at
  the server's URL. No backend or PTY runs locally; everything lives on
  the remote.

## The recommended setup: SSH port-forward

The token is a 9-letter Google-Meet-style code (e.g. `abc-def-ghi`),
which is short enough to dictate or paste but not strong enough for
unrestricted exposure on the open internet. Use an SSH tunnel and keep
the server bound to loopback:

=== "On the server"

    ```sh
    uv run terminux --server --port 8443
    # prints, prominently:
    #
    # terminux server listening — connect with:
    #   http://127.0.0.1:8443/?t=abc-def-ghi
    ```

    The token is persisted to
    `~/.local/share/terminux/server.token` (Linux) or
    `~/Library/Application Support/terminux/server.token` (macOS) with
    mode `0600`. The same URL keeps working across server restarts;
    bookmark it.

=== "On the client (one shell)"

    ```sh
    ssh -L 8443:localhost:8443 server.example.com
    # leave this open for the duration of the session
    ```

=== "On the client (another shell)"

    ```sh
    uv run terminux --connect http://localhost:8443/?t=abc-def-ghi
    ```

    A native terminux window opens. Workspaces, tabs, scrollback:
    everything you see lives on the server. The window is just a
    viewer.

That completes the common case. SSH already solved the hard parts, so
there are no new ports, certificates, or auth layers to manage.

!!! tip "Let the app write the commands for you"
    Running terminux already? Open the command palette (`Ctrl+Shift+P` on
    Linux and Windows, `Cmd+Shift+P` on macOS) and pick **Show remote connection URL**. It
    reports this machine's name and address, tells you whether a tunnel
    is needed, and gives you the `ssh -L` and `terminux --connect` lines
    with the live port and access code filled in, ready to copy.

## Multiple clients

The server's WebSocket fan-out supports multiple subscribers per PTY,
so opening a second `--connect` window from a phone or a second laptop
attaches to the same shells, like `tmux attach` from several places.
Output appears in every window.

A terminal has a single size, though, and windows rarely match. Each
terminal therefore follows the window you are using: typing in it,
clicking or pasting into it, focusing its window, or switching to its
tab makes that window the owner, and the programs inside redraw for its
size. Only the owner's input reaches the shell. A window you are not
using may look garbled while another one owns the terminal; it snaps
back the moment you use it again. (This is tmux's `window-size latest`
policy.)

## What lives where

The **server** keeps this state across client disconnects, sleeps, and
client reboots:

- Workspaces, tabs, their working directories
- Live shells and the processes they're running
- Scrollback (up to 2 MB per tab, replayed on reconnect)
- Sidebar order, font size, UI prefs

The **client** keeps only per-connection state:

- Window position and size: each launch uses the defaults. Per-client
  geometry persistence is not implemented in v1.
- Selection, the fuzzy-switcher's typed query, and other in-page state,
  which reset when the window closes.

## File drag-and-drop

Dropping a file from Finder / Files / your file manager onto a tab works
the same way in `--connect` mode as it does locally. Under the hood the
client POSTs the dropped path(s) to `POST /api/paste-paths` on the
server, which writes the shell-quoted path to the currently active
terminal: the same UX and shell quoting, plus one HTTP round trip.

## Bypassing SSH: `--host 0.0.0.0`

If you trust your network (a home LAN, a Tailscale tailnet, a
WireGuard mesh) and want a direct connection without setting up SSH
forwarding, you can bind the server to a non-loopback address:

```sh
uv run terminux --server --host 0.0.0.0 --port 8443
```

The token is now your only line of defense. The 9-letter token plus the
per-IP rate limiter (10 failures → 60 s lockout) is enough to frustrate
casual brute-force, but it's *not* enough for raw open-internet
exposure. Restrict the route to your trusted network at the OS / router
firewall.

For the open internet, **terminate TLS upstream** (Caddy, nginx, Cloudflare
Tunnel) and put a real auth layer in front. terminux itself does not
ship TLS support and intentionally keeps the token short.

## Security model summary

| Setup | Token strength | Recommended use |
|---|---|---|
| SSH tunnel + loopback (default) | Fine: token guards a loopback-bound port | Any remote use over the open internet |
| `--host 0.0.0.0` on a trusted LAN / VPN | Fine: 43 bits + per-IP lockout | Home network, Tailscale, WireGuard |
| `--host 0.0.0.0` on the open internet | **Not enough**: front it with a real auth layer | Avoid unless you've layered something in front |

## Lifecycle / running it as a service

### `--daemon`: start it and get your prompt back

```sh
terminux --server --daemon --host 0.0.0.0 --public-host devbox.example.com
```

`-d` / `--daemon` starts the server (port 8443 unless you pass `--port`), waits until it answers, prints the URL to connect to, and goes to the background. With `--server` it's headless; without, the desktop window opens as usual, from the background process, and the printed URL lets other machines connect to it too. `--public-host` sets the name in that URL; without it, a `--host 0.0.0.0` server prints this machine's network name, and a loopback server prints `127.0.0.1` for use through an SSH tunnel. If the server can't start (the port is taken, say), the command says why and exits with an error instead of leaving a dead process behind.

The background process logs to `~/Library/Logs/terminux/terminux.log` on macOS and `~/.local/state/terminux/log/terminux.log` on Linux; its output streams (fault dumps, crash tracebacks) go to the same file. Its PID is in `terminux.pid`, in `~/Library/Application Support/terminux/` on macOS and `~/.local/state/terminux/` on Linux. Stop it with `terminux --stop`, which closes its window, if it has one, and waits until it's gone (`kill <pid>` works too); closing the window stops it as well. While a daemon runs, starting another one fails with its PID, since both would share the same saved state. `--daemon` isn't available on Windows.

### With a service manager

To start it at boot or restart it after a crash, let the system's service
manager run `terminux --server` in the foreground (not `--daemon`):

- **systemd user service**: a single `WantedBy=default.target` unit
  that runs `uv run terminux --server`. The token file persists across
  service restarts, so your bookmarked URL keeps working.
- **tmux session**: `tmux new-session -d -s terminux 'uv run terminux
  --server'`. It's trivial to set up and keeps running after logout.
- **macOS launchd**: a per-user `LaunchAgent` plist if you want it to
  auto-start at login.

Pick whichever matches the host's idiom. The watchdog and `--debug` /
`--trace` flags described in [Debugging knobs](../developers/developing.md#debugging-knobs)
work the same in server mode. In the foreground they write to stderr,
which systemd and launchd capture; with `--daemon` they go to the log
file.

## Known limitations (v1)

- **No predictive local echo.** Each keystroke is a WebSocket frame to
  the server; on a high-latency WAN (50 ms+ RTT) typing will feel
  slightly laggy. For high-latency cases, SSH + mosh + tmux gives
  better typing UX. terminux's strength is the workspace/tab model on
  LAN or low-latency WAN.
- **No transport security in terminux itself.** Use SSH or a TLS
  terminator upstream. Do not run `--host 0.0.0.0` straight on the open
  internet.
- **Per-client window geometry** is not persisted yet: every
  `--connect` launch opens at default size.
- **No "rotate token" CLI**: `rm ~/.../server.token` and restart the
  server to force a new one. The previous URL stops working.
