# Developers

This section covers hacking on terminux and scripting against a running instance.

- [**Architecture**](architecture.md): the two-process design (a Python backend owning the PTYs, a TypeScript/Preact UI in a native window), the source layout on both sides, and the key design decisions.
- [**HTTP & WebSocket API**](api.md): the control plane and the per-terminal WebSocket protocol, with auth, payloads, and a curl walkthrough.
- [**Developing**](developing.md): setup, the three test tiers, the four type checkers, and the debugging knobs (`--debug`, `--trace`, the freeze watchdog).
- [**Packaging & distribution**](packaging.md): macOS and Linux bundles, signing, containers, and macOS TCC troubleshooting.

The code lives on [GitHub](https://github.com/abilian/terminux) and [sourcehut](https://git.sr.ht/~sfermigier/terminux) under the Apache 2.0 license. The design history (vision, functional and technical specs, backlog) sits in the repository's `notes/` directory, and `CHANGES.md` records every release.
