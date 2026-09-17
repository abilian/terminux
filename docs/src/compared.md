# Compared to…

Where terminux sits among the tools you may already use. The short version: terminux is a **desktop app for organizing many shells by project**, and it composes with most of the tools below.

## …terminal emulators (iTerm2, kitty, Ghostty, WezTerm, Alacritty)

These are terminal *emulators*: their center of gravity is rendering speed, emulation fidelity, and per-window features. terminux sits one level up. Its center of gravity is the **workspace model**: a persistent, reorderable sidebar of projects, activity and "ready" signals per workspace, and a layout that survives restarts with scrollback included.

terminux gives up some emulator ground for that. Rendering runs on xterm.js in a WebKit view: fast for interactive work, measurably behind kitty or Alacritty on raw throughput. Split panes are still on the roadmap, and the long tail of emulator features (profiles, triggers, tmux integration) is absent.

It answers with the sidebar and its per-project status dots, restart persistence that includes each tab's scrollback, and a client/server mode where your shells outlive your laptop.

## …multiplexers (tmux, screen, Zellij)

A multiplexer runs *inside* any terminal and keeps sessions alive on the machine where it runs. terminux covers part of that ground at the desktop level: shells keep running while the window is closed only in [remote mode](guides/remote.md) (`--server` / `--connect`), where the backend outlives every client, terminals reconnect automatically, and scrollback replays from the server.

The two compose well. tmux remains the right tool inside an SSH session to a box terminux doesn't manage, and running tmux inside a terminux tab works as expected. If your whole workflow already lives in tmux with heavy customization, terminux offers a different trade: GUI-grade workspace navigation and signals in exchange for tmux's scripting depth.

## …cmux

cmux defined the workspace UX terminux follows: the sidebar, the tabs, the "everything where you left it" contract. terminux rebuilds that experience on a different foundation: a Python/Starlette backend owning the PTYs behind a documented [HTTP/WebSocket API](developers/api.md), a TypeScript/Preact frontend, and a codebase small enough to audit in an afternoon. The architectural bet is that a two-process design with a web UI buys web mode, remote access, and testability at an acceptable rendering cost.

## …IDE terminals (VS Code and friends)

An IDE's integrated terminal is scoped to the project the IDE has open. terminux is editor-agnostic and holds *all* your projects at once, whichever editors are involved; pair it with any mix of IDEs, or with none.

## When to choose something else

- You need split panes today, or Windows: both are still on the terminux roadmap.
- Raw rendering throughput is your top criterion: choose kitty, Alacritty, or Ghostty.
- You need sessions to survive on your *local* machine across a backend crash or reboot: a multiplexer holds that ground (terminux restores layout and scrollback, while live processes end with the backend that owns them).
- Your team standardized on tmux scripting: terminux has no equivalent automation surface yet.
