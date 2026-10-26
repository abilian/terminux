# Vision: terminux

**Status:** historical design document. It captures the original intent and scope at the start of the project. Current behaviour and the features that shipped beyond v1 are documented in [`CHANGES.md`](../CHANGES.md), [`docs/`](../docs/), and the active backlog in [`04-backlog.md`](04-backlog.md).

High-level only. Detailed functional and technical specs come in a later round. This captures the intent and the scope.

## One-line pitch

A simple, reliable, cross-platform terminal app with a **Workspaces** sidebar and **tabbed terminals**, implemented in **Python** on a clean two-process architecture.

## In scope (v1)

1. **Workspaces sidebar (left pane).** A persistent list of named workspaces.
   - Each workspace has a **name** the user can edit.
   - Each workspace shows a lightweight **status** indicator (e.g. active/idle/running; the functional spec settles the exact states). Workspaces have no description field.
   - Workspaces and their tabs **persist**: they come back after an app restart.
   - Lifecycle: the user can create, rename, close, and reorder workspaces.
2. **Tabs with multiple terminals.** Each workspace has its own set of tabs; each tab is an interactive terminal with its own shell/PTY. Switching workspaces/tabs preserves running sessions.
3. **Terminal emulation** via a mature web terminal (xterm.js-style) rendered in a webview, fed by raw PTY bytes from the backend.
4. **Cross-platform desktop app** (at least macOS; Linux/Windows desirable).
5. **Local-first:** terminux needs no account, sends no telemetry, and persists to files.

## Explicitly out of scope (v1)

- **Split panes** within a tab: not needed now; *maybe later*. Keep the data model open to it (a per-tab pane tree) but ship single-terminal-per-tab first.
- **Embedded browser**: not wanted (maybe never).
- **File navigator / explorer**: explicitly not wanted.
- **AI / agent integration, git integration, code editor, web preview**: not wanted.
- Heavier machinery found in similar tools: notification hooks, agent credential vaults, a command palette, a remote-SSH daemon, a control socket/automation API.

## Technical direction (high level; details deferred)

- Architecture: **thin web UI (xterm.js) + separate backend process that owns the PTY**, communicating over a narrow, typed IPC surface with **raw-byte streaming** for terminal output, flushed in batches.
- **Backend language: Python.** Tauri is acceptable; since Tauri's native side is Rust, the Python integration approach (Tauri + Python sidecar vs. pywebview vs. Python web backend + webview shell) is an open decision for the technical spec round. *Resolved as pywebview + a loopback Starlette/uvicorn backend; see [`02-technical-spec.md`](02-technical-spec.md).*
- Persistence: a workspace/tab snapshot (no pane tree in v1), stored as local JSON files in the app data dir.
- Adopt proven "good bones": sandboxed UI, background-streaming tabs (no switch jank), shell-side OSC 7/133 integration on a standard emulator.

## Guiding principles

- **Reliability over features.** Correctness and a small, auditable surface matter more than breadth.
- **Small, focused scope.** Ship the workspace + tabbed-terminal core well; resist scope creep (no editor/AI/git/files).
- **Keep the door open** for split panes later without committing to them now.

## Next steps (later rounds)

1. Functional spec: workspace status states, tab/terminal UX details, persistence semantics, keyboard shortcuts.
2. Technical spec: decide the Python ↔ webview integration approach, PTY library, IPC protocol, persistence schema, packaging/distribution.

## Similar projects

terminux draws on ideas from two similar projects:

- **cmux**, a macOS terminal (Swift and libghostty) organized around a workspaces sidebar. terminux follows the same workspace model, as a thin subset, on a cross-platform stack.
- **terax**, a Tauri terminal whose two-process design (a sandboxed web UI rendering xterm.js, plus a separate backend that owns the PTY and streams raw bytes) is the model for terminux's architecture. terminux writes that backend in Python and has no editor, file navigator, AI, or git features.
