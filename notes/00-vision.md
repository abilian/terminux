# Vision: terminux

**Status:** historical design document. It captures the original intent and scope at the start of the project. Current behaviour and the features that shipped beyond v1 are documented in [`CHANGES.md`](../CHANGES.md), [`docs/`](../docs/), and the active backlog in [`backlog.md`](backlog.md).

High-level only. Detailed functional and technical specs come in a later round. This captures the intent, scope, and the two reference projects' roles.

## One-line pitch

A simple, reliable, cross-platform terminal app with a **Workspaces** sidebar and **tabbed terminals**: cmux's workspace UX and terax's clean architecture, implemented in **Python**.

## Inspirations and their roles

- **cmux** (`sandbox/cmux/`) is the *UX reference* for the Workspaces left pane. We want a thin subset of its workspace features. cmux is reportedly buggy and is locked to native macOS/Swift + libghostty; we chose to rebuild on a different technical base. Old reference notes: [`OLD/cmux-features.md`](OLD/cmux-features.md), [`OLD/cmux-architecture.md`](OLD/cmux-architecture.md).
- **terax-ai** (`sandbox/terax-ai/`) is the *architecture reference*. Its Tauri-style two-process design (sandboxed web UI rendering xterm.js + a separate backend process that owns the PTY and streams raw bytes over a typed IPC channel) is the model. We keep that shape and write the backend in Python (terax's is Rust). We do **not** want terax's editor, file navigator, AI, or git features. Old reference notes: [`OLD/terax-features.md`](OLD/terax-features.md), [`OLD/terax-architecture.md`](OLD/terax-architecture.md).

## In scope (v1)

1. **Workspaces sidebar (left pane).** A persistent list of named workspaces.
   - Each workspace has a **name** the user can edit.
   - Each workspace shows a lightweight **status** indicator (e.g. active/idle/running; the functional spec settles the exact states). Workspaces have no description field.
   - Workspaces and their tabs **persist**: they come back after an app restart.
   - Lifecycle: the user can create, rename, close, and reorder workspaces.
2. **Tabs with multiple terminals.** Each workspace has its own set of tabs; each tab is an interactive terminal with its own shell/PTY. Switching workspaces/tabs preserves running sessions.
3. **Terminal emulation** via a mature web terminal (xterm.js-style) rendered in a webview, fed by raw PTY bytes from the backend.
4. **Cross-platform desktop app** (at least macOS; Linux/Windows desirable, following terax's reach).
5. **Local-first:** terminux needs no account, sends no telemetry, and persists to files.

## Explicitly out of scope (v1)

- **Split panes** within a tab: not needed now; *maybe later*. Keep the data model open to it (terax's pane-tree is the reference) but ship single-terminal-per-tab first.
- **Embedded browser**: not wanted (maybe never).
- **File navigator / explorer**: explicitly not wanted.
- **AI / agent integration, git integration, code editor, web preview**: not wanted.
- cmux's heavy machinery: notification hooks, agent vault, command palette, remote-SSH daemon, control socket/automation API.

## Technical direction (high level; details deferred)

- Architecture modeled on terax: **thin web UI (xterm.js) + separate backend process that owns the PTY**, communicating over a narrow, typed IPC surface with **raw-byte streaming** for terminal output (terax's batched-flush channel pattern).
- **Backend language: Python.** Tauri is acceptable; since Tauri's native side is Rust, the Python integration approach (Tauri + Python sidecar vs. pywebview vs. Python web backend + webview shell) is an open decision for the technical spec round. *Resolved as pywebview + a loopback Starlette/uvicorn backend; see [`technical-spec.md`](technical-spec.md).* Original analysis in [`OLD/terax-architecture.md`](OLD/terax-architecture.md) § "Translating to Python".
- Persistence: cmux-style workspace/tab snapshot, simplified (no pane tree in v1), stored as local JSON in the app data dir (terax's file-based-store approach).
- Adopt terax's "good bones": sandboxed UI, background-streaming tabs (no switch jank), shell-side OSC 7/133 integration rather than a custom emulator.

## Guiding principles

- **Reliability over features.** The motivation for rebuilding cmux is its bugginess; correctness and a small, auditable surface matter more than breadth.
- **Small, focused scope.** Ship the workspace + tabbed-terminal core well; resist scope creep (no editor/AI/git/files).
- **Keep the door open** for split panes later without committing to them now.

## Next steps (later rounds)

1. Functional spec: workspace status states, tab/terminal UX details, persistence semantics, keyboard shortcuts.
2. Technical spec: decide the Python ↔ webview integration approach, PTY library, IPC protocol, persistence schema, packaging/distribution.
