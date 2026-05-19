# terminux

**A fast, reliable, cross-platform terminal — organized the way you actually work.**

Workspaces on the left. Tabbed terminals in the middle. Everything where you
left it, even across restarts.

![terminux — workspaces sidebar and a tabbed terminal running a test suite](images/main-window.png){ loading=lazy }

---

## The idea

You don't have one project. You have several — each a different directory, a
different mental context, a different set of running shells. terminux gives each
of them a home: a **workspace**. Workspaces and their tabs persist across
restarts, so reopening the app drops you straight back into your layout.

terminux takes the workspace UX of [cmux](https://github.com/) and rebuilds it
on a clean, auditable two-process architecture inspired by *terax* — written in
**Python**, with **reliability over features** as the guiding principle. No
account, no telemetry, no AI, no editor. Just a terminal that respects your
flow.

## Highlights

- **Workspaces sidebar** — a persistent, reorderable list of named workspaces,
  each with an automatic status dot.
- **Tabbed terminals** — multiple live PTY shells per workspace; background tabs
  keep streaming with no switch jank.
- **Persistence** — workspaces, tabs, window geometry, sidebar state, font size,
  and per-shell working directories survive restarts.
- **Keyboard-first** — workspace jumps, fuzzy quick-switcher, find-in-terminal,
  font zoom. See [Keyboard shortcuts](keyboard-shortcuts.md).
- **Attention routing** — background activity indicators; BEL / `OSC 9` on an
  off-screen tab raises a badge that bubbles up to its workspace.
- **Local-first & hardened** — loopback-only by default, per-session auth token,
  CSP and security headers, atomic versioned persistence.

## Where to go next

<div class="grid cards" markdown>

- :material-rocket-launch: **[Getting started](getting-started.md)** — install,
  run, and package terminux.
- :material-tab: **[Workspaces & tabs](workspaces-and-tabs.md)** — the core
  model and how persistence behaves.
- :material-keyboard: **[Keyboard shortcuts](keyboard-shortcuts.md)** — every
  binding.
- :material-sitemap: **[Architecture](architecture.md)** — the two-process
  design.

</div>

!!! note "Status — v1 preview"
    terminux is a v1 prototype. The workspace + tabbed-terminal core works well;
    split panes, detach, Windows PTY, and scrollback persistence are not done
    yet. See the [FAQ](faq.md) and `notes/technical-spec.md` §11–§14.
