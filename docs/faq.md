# FAQ

## What state survives a restart?

The **layout**: workspaces, tabs, window geometry, sidebar width/collapsed
state, terminal font size, and each shell's last working directory. On restart
every tab respawns a **fresh shell** in that directory (falling back to the
default if it no longer exists).

Running processes and scrollback are **not** restored — terminux persists
structure, not live processes.

## Is scrollback persistence planned?

Yes, it's a known roadmap item, along with split panes, client/server detach,
and a Windows PTY backend. See `notes/technical-spec.md` §11–§14.

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
features are explicitly out of scope (see `notes/vision.md`).

## Why is the macOS app blocked by Gatekeeper?

The `.app` is **ad-hoc signed only**. On a Mac other than the build machine,
right-click → **Open** the first time, or sign with a Developer ID and notarize.
See [Packaging & distribution](packaging.md).

## Do I need Node.js to run terminux?

Only to *build* or change the frontend. The build output is committed to
`src/terminux/web/static/`, so running from source needs only Python + `uv`.

## What are cmux and terax?

terminux's two reference projects: **cmux** is the UX reference for the
Workspaces sidebar; **terax** is the architecture reference (two-process,
PTY-owning backend, raw-byte streaming). terminux reimplements a focused subset
in Python. Details in `notes/`.
