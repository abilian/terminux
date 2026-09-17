# Guides

Pick the guide that matches what you are trying to do.

## Keep many projects in the air

[**Workspaces & tabs**](workspaces-and-tabs.md) is the core model: one workspace per project, automatic naming from the working directory, status dots, activity tracking, and what persistence restores after a restart and what it cannot.

## Know when a task finishes

The same guide's [Working vs ready](workspaces-and-tabs.md#working-vs-ready) section explains the amber/green traffic light. To make the green dot exact, add the three-line snippet from [**Shell integration**](shell-integration.md) to your shell config.

## Work on another machine

[**Remote access**](remote.md): run `terminux --server` on a host, `terminux --connect` on your laptop, and your shells outlive lid-closes, network hops, and client restarts. Includes the SSH-tunnel recipe, multi-client attach, and running the server under systemd.

## Drive everything from the keyboard

[**Keyboard shortcuts**](keyboard-shortcuts.md) lists every chord on both platforms: workspace jumps, the two palettes, find-in-terminal, zoom, and the conventions that keep raw `Ctrl` free for your shell.
