# FAQ

## What state survives a restart?

- The **layout**: workspaces, tabs, window geometry, sidebar width/collapsed
  state, terminal font size, and each shell's last working directory.
- Each tab's **scrollback** (last ~5000 lines), replayed into a fresh terminal
  on restart with a dim `──── session resumed @ <time> ────` separator so the
  boundary between old output and the new shell is obvious.

Every tab respawns a **fresh shell** in the saved directory — running
processes are *not* restored. terminux persists what was on screen, not what
was running.

## Can I turn scrollback persistence off?

Yes. It defaults to **on**, capped at 2 MB per tab, and the files are deleted
when the tab or workspace is closed. To disable it entirely:

```sh
curl -X PATCH "http://127.0.0.1:<port>/api/ui?t=<token>" \
  -H 'Content-Type: application/json' \
  -d '{"scrollback_persist": false}'
```

The pref is persisted server-side, so it sticks across restarts.

## What about split panes and Windows?

Both are still on the roadmap, along with client/server detach.

## Does terminux work on Windows?

Not yet. macOS and Linux are supported; the Windows PTY backend is deferred.

## Is it safe to expose terminux on the network?

By default the backend binds to **loopback only** and authenticates every
request and WebSocket with a per-session token. If you bind beyond loopback
(`--host 0.0.0.0`), that token is the **only** authentication — anyone with the
URL gets a shell. Keep the URL private and prefer loopback.

## Does terminux send any telemetry or need an account?

No. terminux is **local-first**: no account, no telemetry, file-based
persistence only.

## Does it include an editor / AI / git integration?

No, and by design. terminux deliberately keeps a small, auditable surface —
workspaces and tabbed terminals done well. Editor, AI, git, and file-navigator
features are out of scope.

## Why is the macOS app blocked by Gatekeeper?

The `.app` is **ad-hoc signed only**. On a Mac other than the build machine,
right-click → **Open** the first time, or sign with a Developer ID and notarize.
See [Packaging & distribution](packaging.md).

## Do I need Node.js to run terminux?

Only to *build* or change the frontend. The build output is committed to
`src/terminux/web/static/`, so running from source needs only Python + `uv` (or `pip`).
