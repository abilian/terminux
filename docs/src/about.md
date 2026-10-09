# About

terminux is a cross-platform desktop terminal organized around a **workspaces sidebar** and **tabbed terminals**. It builds that workspace-first UX on a small, auditable two-process architecture: a Python backend that owns the real PTYs, and a TypeScript web UI rendered in a native window.

## Philosophy

- **Reliability over features.** A terminal hosts your live shells; a freeze or a lost session costs real work. terminux ships fewer features and hardens the ones it has: non-blocking terminal I/O end to end, a watchdog that diagnoses its own stalls, automatic reconnection, and atomic, versioned persistence.
- **Local-first.** No account and no telemetry. All state lives in local files you can read (`state.json` plus one scrollback file per tab). The network surface is loopback-only unless you opt out.
- **A terminal, nothing else.** There is no editor, AI, git client, or file navigator; those already live in your shell. Keeping the surface small keeps it auditable.
- **Respect the platform.** Shortcuts follow each platform's conventions (`Cmd` on macOS, `Ctrl+Shift` on Linux, matching GNOME Terminal and friends), raw `Ctrl` chords flow to the shell, and macOS quirks (press-and-hold, TCC) are handled the way native terminal apps handle them.

## Status

terminux is a **0.10 preview** for macOS, Linux and Windows. Working today: the workspace/tab core with working-and-ready signals, layout and scrollback persistence, remote access with automatic reconnection, keyboard-first navigation, and macOS and Linux bundles. Split panes, a standalone Windows bundle, and multi-user auth for the open web are still ahead. The [changelog](https://github.com/abilian/terminux/blob/main/CHANGES.md) records every release in user-facing terms.

## License and source

terminux is free software under the **Apache 2.0** license. Development happens in the open:

- GitHub: [abilian/terminux](https://github.com/abilian/terminux)
- sourcehut: [~sfermigier/terminux](https://git.sr.ht/~sfermigier/terminux)

Bug reports are welcome on the [issue tracker](https://github.com/abilian/terminux/issues); a report is most useful with the output of a `--debug` run (see [Debugging knobs](developers/developing.md#debugging-knobs)).

## Credits

terminux's design draws on similar projects; [Compared to…](compared.md) explains where it sits among them. Under the hood terminux stands on [xterm.js](https://xtermjs.org/), [Starlette](https://www.starlette.io/), [pywebview](https://pywebview.flowrl.com/), and [Preact](https://preactjs.com/).
