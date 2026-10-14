# Lessons learned

Concrete, transferable lessons surfaced while building (and debugging) terminux. Organized by area. Each entry is "symptom → cause → fix" so future-you can grep for the symptom.

## Terminal emulation & xterm.js

### BEL is overloaded; a naive bell detector misfires on every title update

**Symptom.** The "ready" dot on a workspace fires constantly while a tool like Claude Code is working but not waiting for input. (Originally surfaced as the now-removed 🔔 badge; same root cause.)

**Cause.** `\x07` (BEL) terminates `OSC 0/2;<title>\x07` title-update sequences. Any "fire attention on `\x07` in PTY output" check trips on every shell-title change.

**Fix.** Stateful per-Terminal scanner that walks the byte stream tracking GROUND/ESC/OSC states across reads. Only a BEL *outside* an OSC counts as a real bell. (`core/terminal.py::_AttentionScanner`.) Same scanner usefully extends to `OSC 9` (iTerm2 notification) and `OSC 133;D` (shell-integration "command finished"). All three signals now feed the workspace's `has_unseen_output` → green "ready" dot via `AppController._mark_ready` (`server/controller.py`).

### "Ready" needs more than just `OSC 133;D` to work without shell integration

OSC 133 (shell integration) cleanly demarcates command boundaries: `C` = command start, `D[;exit]` = command end. Gate the fire on a minimum duration between matching `;C` and `;D` (~2s) so background `cd`s don't ring. But shell-integration is opt-in; for users without it, we also need a kernel-level signal: a `tcgetpgrp`-based busy→idle transition that lasted at least ~5s. Both paths reach the same end state; `AppController.poll_busy_transitions` handles the second. Never make a UX feature depend solely on opt-in shell support.

### "Output happened" is a weak attention signal; collapse it into "task finished" instead

The original "any output → unseen" mark fired on Claude Code's cursor blinks and other cosmetic noise, painting the dot green for workspaces that weren't actually ready. The current model only flips the workspace-level "ready" flag on the strict sources above (BEL outside OSC, OSC 9, OSC 133;D ≥ 2s, or kernel-level busy→idle ≥ 5s). The finer-grained "output happened in this tab" indicator remains, at the *tab* level only.

### xterm.js `term.write()` is async

**Symptom.** Restored scrollback "almost works" but layout shifts depending on timing of subsequent calls.

**Cause.** `write(data, callback?)` queues bytes for the parser; the callback fires when parsing is complete. Anything that mutates buffer state synchronously after `write()` (notably `term.resize()`, which `FitAddon.fit()` calls) can land *during* parse, with the new dimensions taking effect mid-stream.

**Fix.** `await new Promise<void>(resolve => term.write(data, () => resolve()))` before any resize.

### Restore content size must match the captured buffer's size

Per SerializeAddon's docs: *"write the serialized data into a terminal of the same size in which it originated from and then resize it after if needed."* Construct `new Terminal({cols, rows})` at the *saved* dimensions, write, then call `fit()`. xterm's resize reflow is partial: it can wrap on shrink but cannot reliably un-wrap on grow. Going from default 80×24 → 220 cols leaves wrapped lines visibly broken.

### `SerializeAddon.serialize({ excludeAltBuffer: true })` is non-negotiable for replay

**Symptom.** Sessions where an alt-screen TUI was active restore with garbled content; the new shell's prompt appears inside the alt buffer.

**Cause.** Default `excludeAltBuffer: false` emits `\x1b[?1049h` (enter alt screen) + alt-buffer contents but *no matching* `\x1b[?1049l`. Replayed into a fresh xterm, that flips the new terminal into alt-screen mode permanently.

**Fix.** Always pass `excludeAltBuffer: true`. The alt buffer of an exited program is fundamentally unrecoverable anyway (the program tore it down on exit). Say so in the docs; iTerm2's session restoration has the same limit.

### Also set `excludeModes: true` on restore

It stops the captured session's terminal modes (application keypad, bracketed paste, mouse tracking and the like) from leaking into the new shell. The fresh shell reasserts whatever it needs.

### Two clients on one PTY: one size, so one owner

**Symptom.** With a `--connect` window open on a second machine, terminals on the first one fill with text in the wrong places (shell, Claude Code, any TUI). Switching tabs doesn't help; only closing the tab and opening a new one does.

**Cause.** A PTY has exactly one size and every attached client could set it, last writer wins. The remote window sent its (smaller) size on attach; the programs redrew for it while the desktop xterm still rendered at its own width. The desktop never took the size back because xterm's `onResize` fires only when its own dimensions *change*, and refocusing or switching tabs recomputes the same ones. A second, quieter effect: every attached emulator auto-answers the program's queries (CPR, DA, kitty keyboard), so the shell got duplicate answers, one of them describing the wrong screen.

**Fix.** tmux's `window-size latest`: the client in use owns the terminal. The server records each client's size but applies only the owner's, drops non-owner input (which in practice is only those auto-answers), and moves ownership on an explicit `claim`. The frontend sends a claim on keydown, before the bytes the key produces (both travel on the same websocket, so they stay ordered). It also claims on mousedown and paste in the capture phase, on window focus, on tab activation, and on reconnect, and it makes the last three claims only when the tab is on screen in a focused window. When the owner disconnects, the latest remaining client takes over. Proved with two real websocket clients in an integration test and two different-size browser pages running `stty size` in an e2e test; both fail on the old code. In general, any per-terminal state with a single physical value (size, focus reporting, mouse mode) needs an explicit arbiter once more than one client can attach.

## Persistence (Python)

### `Path.read_text()` silently rewrites `\r\n` → `\n`

**Symptom.** Each row of restored ANSI content lands one column further right than the previous (a cumulative LF-without-CR "staircase").

**Cause.** `Path.read_text(encoding="utf-8")` defaults to `newline=None`, which enables universal-newlines mode and strips every CR. SerializeAddon emits `\r\n` between rows; without the CR, the cursor moves down but doesn't reset the column.

**Fix.** `path.read_bytes().decode("utf-8")` for any persisted text that contains protocol-significant CRs (terminal streams, raw HTTP, anything binary-adjacent). Or `read_text(newline="")` if you want the text overload. A regression test in `tests/a_unit/test_persistence.py::test_scrollback_preserves_crlf` guards this; keep it.

### Version your on-disk envelope, even for "trivial" formats

Going from raw-ANSI-bytes (v1) to `{"v":2,"cols":N,"rows":N}\n<ansi>` (v2) needed an explicit migration decision: discard v1 on read because the bug we were fixing made the old payloads unsafe. A single-line JSON header is enough. Checking whether the first byte is `{` tells v2 apart from legacy files.

### Bound on-disk caps generously and keep the tail

Each tab's scrollback can easily hit hundreds of KB once ANSI escapes are included. We cap at 2 MB/tab and keep the *tail* (most recent output) when content exceeds the cap. Head-trimming would keep ancient context the user doesn't care about.

### Always regex-gate filenames built from user-controllable ids

Tab ids are server-generated uuid4s today, but a single `^[A-Za-z0-9_-]+$` guard on any path component constructed from a string defuses entire classes of path-traversal bugs cheaply.

## macOS specifics (pywebview / WKWebView)

### `window.open()` is a no-op in pywebview

**Symptom.** `Cmd+click` on URLs in the terminal does nothing.

**Cause.** WKWebView's default UI delegate doesn't handle JavaScript-opened windows.

**Fix.** Route external URL opens through a backend endpoint that spawns `open` (macOS) or `xdg-open` (Linux) via `subprocess.Popen([opener, url])`. Whitelist schemes (`{http, https, mailto}`), reject `file://` / `javascript:` / `data:`. Resolve the opener via `shutil.which()`. This also unifies behavior with `--no-window` browser mode.

### Press-and-hold hijacks key repeat

**Symptom.** Holding `j`/`k`/anything in vim pops the accent-picker overlay, and the key doesn't repeat.

**Cause.** WKWebView's text-input layer hooks the same press-and-hold path Cocoa uses for native text fields; xterm.js focuses a hidden `<textarea>` that triggers it.

**Fix.** At window startup, set `NSUserDefaults.standardUserDefaults().setBool_forKey_(False, "ApplePressAndHoldEnabled")` via PyObjC. Every native terminal app does this. The value persists for the host process's bundle id (`.app` keeps its own prefs; dev mode shares Python's).

### TCC ("Files and Folders" / "Full Disk Access") is per-responsible-process and lazy

**Symptom.** Shells inside the app suddenly start emitting `Operation not permitted` / `file system sandbox blocked open()` partway through a session, on Homebrew/nvm paths that worked earlier.

**Cause.** macOS evaluates TCC scope at *access time*, not process start. The first shells often don't touch the protected location (typically a removable volume where the user relocated Homebrew). The wall only appears when a new tab re-sources `.profile` and something `dlopen`s a library from `/Volumes/<external>/...`.

**Fix.** Grant the TCC-responsible parent of the shells access to the volume. Identify it with `ps -o pid,ppid,command -p $(pgrep -f <app>)`; under pywebview it's usually the embedded Python (Terminal.app is the usual wrong guess). macOS only re-evaluates scope on process start, so the app must be restarted after granting.

### App Nap looks exactly like an event-loop freeze to a heartbeat watchdog

**Symptom.** A `nohup` log full of "event loop unresponsive" warnings (326 in one 4.4 MB log, stalls up to 405 s), each with a full stack dump, on a machine that was awake and an app that felt fine whenever you looked at it.

**Cause.** macOS App Nap: when an app's window is covered or hidden, or the display sleeps while the Mac stays awake, the OS stretches its timers and lowers its CPU priority. The asyncio heartbeat goes stale, so the watchdog concludes the loop is frozen. Three tells separate this from a real freeze. First, there is no hot spot: a real wedge parks the loop in one frame in every dump, while here it was idle in `select()` or scattered across ordinary frames. Second, the watchdog thread itself was starved: consecutive warnings came 60 to 330 s apart, where the watchdog normally warns every 10 s. Third, it isn't system sleep, because Python's `time.monotonic()` on macOS is `mach_absolute_time()`, which stops during sleep.

**Fix.** Opt out of App Nap while the window is open: `NSProcessInfo.processInfo().beginActivityWithOptions_reason_(NSActivityUserInitiatedAllowingIdleSystemSleep, …)`, holding the returned token for the window's lifetime (dropping it re-enables App Nap). The "allowing idle system sleep" variant matters: the app must never keep the Mac awake. Separately, the watchdog now measures its own oversleep: if its 1 s sleep overran by more than the stall threshold, the whole process was paused, so it logs one line with no dump and measures any stall only from the resume. A monitor that cannot tell "my patient stopped" from "I was asleep too" will cry wolf.

### PyObjC's Foundation module needs static-checker exemption

`Foundation` is a dynamic Cocoa bridge; static type checkers can't introspect it. Add to mypy/pyrefly `ignore-missing-imports` lists; inline `# ty: ignore[unresolved-import]` and `# pyrefly: ignore[missing-module-attribute]` on the specific imported symbol.

### A forked child that doesn't exec gets a blank window

**Symptom.** `terminux -d` printed its URL and the window opened, but the page stayed blank. The log had `NSXPCSharedListener … Connection invalid` and `Connection Invalid error for service com.apple.hiservices-xpcservice`.

**Cause.** `--daemon` went to the background with a double `fork()` + `setsid()` and kept running the same interpreter. On macOS, a child of `fork()` that doesn't `exec` can't use the system's XPC services, and WKWebView needs them to start its web content process. A headless server doesn't notice, which is why the integration tests (with no real window) kept passing.

**Fix.** The launcher re-runs the same command as a new process (`subprocess.Popen(..., start_new_session=True)`) and passes it the readiness pipe's write end through `TERMINUX_DAEMON_READY_FD` (`app.py::_daemonize`). Any background-a-GUI trick on macOS needs an `exec`.

## Windows specifics (pywebview / WinForms)

### pywebview's `icon=` must be a `.ico` on Windows

Symptom: first `uvx terminux` on Windows dies right after "server ready" with a .NET `System.ArgumentException: Argument 'picture' must be a picture that can be used as a Icon`. Cause: pywebview's docs say `icon=` is GTK/Qt only, but the WinForms backend also uses it, passing the path to `System.Drawing.Icon(path)`, which rejects PNG. Fix: ship `assets/icon.ico` and pick the file per platform (`app.WINDOW_ICON`).

### WebView2 has no Edit menu, no context menu, and refuses `navigator.clipboard.readText()`

Symptom: no way to copy or paste on Windows (and Linux); after adding an Edit menu, Edit → Paste still did nothing while `Ctrl+V` worked. Cause: pywebview builds an Edit menu only on macOS and disables the context menu outside `--debug`; a menu click gives the webview no keystroke for a native paste, and WebView2 denies the clipboard read permission that pywebview never handles. Fix: keyboard paste keeps the webview's default action (stop propagation so xterm doesn't send ^V, but don't `preventDefault`); the Windows menu Paste reads `CF_UNICODETEXT` in Python (`terminux/clipboard.py`, ctypes) and calls `window.terminux.pasteText()`.

## Frontend (WebKit / browser)

### `fetch({ keepalive: true })` for in-flight requests during page unload

Used for the final scrollback flush on `pagehide` / `beforeunload`. More reliable than plain `fetch` for unload scenarios (the browser keeps the connection alive after navigation). `navigator.sendBeacon` is more reliable still but doesn't support PUT.

### `Cmd/Ctrl+click` is the convention; plain click on URLs is hostile

iTerm2, Terminal.app, Hyper all gate URL opens on a modifier. Plain-click means a stray click during a Cmd-Tab / scroll can navigate. xterm's official `@xterm/addon-web-links` accepts a custom click handler; gate it on `event.metaKey || event.ctrlKey`.

## UX / naming

### Status labels that don't match meaning are a chronic bug source

The sidebar dot was `running` but actually meant "unseen output since you last viewed this workspace"; nothing tracked live activity under the hood. Confusing label → user thinks the app is broken. A rename matters even when behaviour doesn't change. Hovering a status indicator should explain what it means (`title` attribute is cheap).

Sequel to this lesson: the sidebar then also showed a 🔔 attention badge (BEL/OSC 9/OSC 133;D) *in addition to* the green "unseen" dot. From the user's seat both meant "look here later" but had different visual treatments and different trigger conditions. Collapsed both into a single green "ready" dot in 0.7.0, which gives one signal with stricter sources. **Two indicators that mean roughly the same thing are worse than one indicator with a clear definition.**

### Discoverable keyboard shortcuts ≠ documented keyboard shortcuts

`Cmd+1..9` to jump to workspaces was implemented from day one, but nothing showed it and users had no idea. A small keycap badge next to the first nine workspace names made the shortcuts obvious with no behavior change.

## Process

### Discuss non-trivial features before implementing

Before implementing a non-trivial feature, write down its 2–3 open design decisions (defaults, tradeoffs) and settle them first. That costs less than redoing work after a wrong default.

### Say up front what *can't* be restored

Once you commit to "persist what was on screen," users will reasonably ask "why didn't my Claude Code session come back?" Alt-screen content is genuinely unrecoverable; saying so up front (in docs, in commit messages) is better than silent best-effort behavior that looks like a bug.

### One bug fix can rebake corruption into persisted state

After fixing the CR-stripping read path, the on-disk scrollback was still corrupt because a previous run had captured a corrupted-on-read buffer back to disk. Always include a one-line wipe instruction in the fix's commit message / docs:

```sh
rm -rf "$HOME/Library/Application Support/<app>/<bad-state-dir>"
```

## Server-side concurrency

### Any sync call from an `async def` handler can freeze the whole server

The asyncio loop runs **single-threaded**. A coroutine that calls a synchronous, blocking function does not give other coroutines a chance to run until that function returns. Worse: anyone *waiting* on the same blocked resource (the loop's own ticker, uvicorn's accept callback, every other PTY's `_pump_in`/`_pump_out`) is also frozen. The visible symptoms are identical across many root causes: terminals stop accepting keystrokes and new HTTP/WebSocket connections hang, but tab switching still works because that's pure frontend.

This project hit three real failure modes, all the same shape:

| Site | Trigger | Fix |
| --- | --- | --- |
| `_workspace_label` → `term.cwd()` → `subprocess.run([lsof, ...])` under `ctl.lock` | Wedged mount put lsof in D-state; `subprocess.run` couldn't kill it. Loop blocked on lock the next tick. | Replaced lsof with `libproc.proc_pidinfo(PROC_PIDVNODEPATHINFO)` via ctypes: a pure kernel call that can't hang on bad fds. |
| `patch_workspace` / `patch_ui` / `put_scrollback` calling `ctl.save()` and friends directly | Slow `os.fsync` on APFS under load. | Every async handler wraps its lock+I/O block in `asyncio.to_thread`. |
| `_pump_in` → `term.write` → `os.write` on the PTY master fd | Paste from an HTML page filled the kernel's PTY input buffer (~4 KB on macOS) faster than the shell drained it. `os.write` parked the loop thread. | `await asyncio.to_thread(term.write, data)`, which shrinks the blast radius from "whole server" to "one terminal." |

**Rule of thumb**: an `async def` handler should never call a synchronous function that touches disk, the network, an fd of unknown drain rate, or any non-`asyncio.Lock` lock. If a sync call is necessary, wrap it in `asyncio.to_thread`. Defense in depth: a watchdog that auto-dumps per-thread stacks (`terminux.diagnostics.start_watchdog` + `faulthandler.dump_traceback(all_threads=True)`) made the third case findable; without it, the user would have been guessing again.

This **landed on 2026-07-29**, after a field freeze of exactly this shape (a blocking master read parking the loop). The master fd is now non-blocking (`UnixPty.__init__`). `_on_readable` treats `BlockingIOError` as a spurious wakeup and returns; the trap is that its `except OSError` branch means child-exit, so an unhandled EAGAIN would have closed the tab. `UnixPty.write` drains via a `select()`-paced loop that handles EAGAIN and partial writes on the worker thread. **Remaining followup**: a per-Terminal async write queue with overflow drop. Even now, a permanently stuck shell parks one `to_thread` worker in `select()` forever. Drop-on-overflow would make the system fully resilient, with the same model the output-fanout subscribers already use.

### A lock held across fsync is the loop freeze with extra steps

**Symptom.** 0.7.1 moved every handler's disk I/O into worker threads, yet the loop could still stall for the duration of a slow fsync.

**Cause.** The workers held `ctl.lock` *while* fsyncing (`save()` ran `save_state` inside the lock), and one loop-side path (`spawn` → `ensure_terminal`) acquired the same lock. Off-loading I/O to a thread buys nothing if the loop later queues behind the lock that thread is holding across the I/O.

**Fix.** We now enforce two rules. First, hold `ctl.lock` only around in-memory work: `save()` snapshots `to_json()` under the lock and writes and fsyncs outside it. Second, nothing on the loop thread performs blocking work while holding it: PTY fork/exec happens in a worker (`ensure_terminal` is two-phase, and only `add_reader` runs on the loop). Grep test: any `with self.lock` block that reaches `os.fsync`, `subprocess`, or a fork is the bug reappearing.

### An unauthenticated index that embeds the token defeats the token

**Symptom.** Every route checked `?t=` except `/`, which served the HTML with the session token substituted in. In `--host`/`--server` mode, `curl http://host:port/` returned the token to anyone who could reach the port.

**Cause.** Auth lived as a per-handler guard, so the one handler without it failed *open*. The failure was invisible: everything worked normally for legitimate clients.

**Fix.** Token check moved into the middleware, fail-closed, with an explicit public allowlist (`/assets/` only). A new route now cannot forget auth. The same audit taught a corollary: on loopback, exempt local IPs from the brute-force lockout. All local clients share `127.0.0.1`, so one stale browser tab polling with an old token would lock out the real window (self-DoS).

### Old WebKit needs `ws://` spelled out in CSP, and dependency floors are part of your support floor

**Symptom.** On Big Sur's WKWebView the app worked (sidebar, tabs, API calls), but every terminal showed "(exited)". The same backend worked fine in a modern Firefox.

**Cause.** Two independent floors were raised silently. (1) A routine dependency refresh moved xterm.js to 6.x, whose minimum browser is newer than Safari-14-era WebKit, so terminal construction died. (2) After pinning xterm back, the next layer surfaced: `connect-src 'self'`. Per CSP3, `'self'` covers same-origin websockets (modern engines agree). Old WebKit and Firefox reject `ws://` unless the origin is listed explicitly, so `new WebSocket()` threw `SecurityError` at attach.

**Fix.** We pinned xterm to the 5.x line and set Vite's `build.target` explicitly to `["es2020", "safari14"]`, with a comment naming the support floor. The CSP is now built per request with `ws://<host> wss://<host>` added to `connect-src` (the Host header is validated before interpolation into the header). `--debug` cracked it: it now enables pywebview's inspector (right-click → Inspect Element). The blocked connection had stayed invisible until the console reported it. The desktop app's browser is *the OS's WebKit*, so every frontend dependency bump and build-target default is silently a support-matrix decision. The frontend must also treat any synchronous `new WebSocket()` throw as a retryable connection failure.

### Field runbook: unfreeze a live server without killing it (macOS)

**Symptom.** A running (pre-fix) instance freezes mid-session: every terminal dead, HTTP unresponsive, tab switching still works. Long-running jobs in other tabs must keep running, so `kill` is not an option. Executed successfully twice against a live 0.7.0 with 20 shells.

**Cause.** The loop thread is parked in a blocking `os.write` to one PTY master whose kernel input queue is full (paste into a program that stopped reading). Classic mutual deadlock: the frozen loop also stops draining that PTY's output, so the foreground process blocks on *its* writes and never reads the input queue.

**Fix (runbook).**

1. Confirm: `sample <pid> 1` → one thread stuck in `os_write → _Py_write_impl → write`.
2. Find the fd: `lldb --batch -p <pid>`, read the blocked thread's frame-0 registers: `x16 == 4` (SYS_write), `x0` = fd, `x2` = bytes remaining. Detach.
3. Map fd → tab with `lsof -nP -p <pid>`. The fd's device minor `15,N` means slave `ttysNNN`; `ps -axo pid,ppid,stat,tty,command | awk '$4=="ttysNNN"'` shows the stuck tab's shell and foreground process (often a wedged editor or a zombie the shell can't reap).
4. Unblock. Do **not** try to open `/dev/ttysNNN` from outside: macOS revokes the devfs node for ptmx slaves (ENOENT). Instead attach lldb to the *shell* on that tty (expendable, unlike the backend) and make it operate on its own controlling terminal:
   - **Blocked in `write`** (`x16 == 4`; input queue full): `expr (int)tcflush(0, 1)` (TCIFLUSH), a few times with ~150 ms gaps. Each flush frees input-queue space; the backend's blocked write completes, the loop resumes, drains the PTY output, and the stuck tab self-heals. Only the stuck pasted bytes are lost.
   - **Blocked in `read`** (`x16 == 3`; the loop did a blocking read on a master with no data, seen once after a readable-event race): the mirror move is to feed the master one byte of *output* with `expr (int)write(1, (char*)"\0", 1)`. A NUL renders as nothing in xterm.js; the blocked read returns with 1 byte and the loop resumes. One shot was enough; if it re-parks on the next empty read, the fd is being polled in a read-until-EAGAIN loop and needs `O_NONBLOCK` set via lldb before feeding again.
5. Verify: `curl` the token URL (should answer in ms), re-`sample` and check no thread is in `os_write`/`os_read`. Unreaped zombies under the backend get collected once the loop runs again (or hang around harmlessly).

Cruder fallback: killing the foreground process *and* its shell closes the slave's last holder, which hangs up the pty and wakes the blocked writer with EIO, at the cost of that whole tab. Never close the pywebview window: `win.events.closed → _shutdown` takes down the server and every shell. To re-attach dead UI terminals afterwards (frontends older than 0.7.2 have no auto-reconnect; newer ones redial on their own), open the token URL in a regular browser; the PTY fan-out supports multiple subscribers. On 2026-08-22, on an old Intel/Big Sur MacBook, a kernel-level `close(2)` stall froze the loop only *transiently* at startup, but that was enough to kill every websocket. The "hang" the user saw was the unreconnected frontend outliving a backend that had already recovered. The frontend reconnect closes that whole failure class.

## Tooling

### Each type checker has its own ignore syntax

| Tool | Inline ignore |
| --- | --- |
| mypy | `# type: ignore[code]` |
| ty | `# ty: ignore[code]` |
| pyrefly | `# pyrefly: ignore[code]` |
| ruff | `# noqa: code` |

When one symbol trips all of them, comments stack on the same line. Avoid this by adding the module to the corresponding `ignore-missing-imports` lists in `pyproject.toml` where possible.

### `subprocess.Popen([argv])` is safe but bandit's S404 still fires

The S404 rule flags the *import*, not the usage. Acknowledge with `# noqa: S404 — argv form only, no shell, opener path resolved via shutil.which()` to keep the rationale next to the import.

### Hooks (pre-commit, ruff) can disagree with your local lint pass

`make lint` runs ruff + ty + pyrefly + mypy; pre-commit runs ruff at a different version. Pin both, or accept that pre-commit may surface new issues at commit time. Don't `--no-verify` past hook failures; fix or pin.
