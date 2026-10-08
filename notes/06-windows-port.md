# Windows port

Status (2026-10-08): **client mode works** (`terminux --connect <url>`): the window icon, link opening and the data folder are fixed. **Terminals on Windows don't**: `spawn_pty` raises `NotImplementedError`. This note is the plan for the rest. It refines §10 of `02-technical-spec.md`.

## What's Unix-only today

Every item is in `core/pty_backend.py` or `core/terminal.py`. The server, the protocol, the frontend and persistence are portable.

| Area | Unix today | Where | Windows gap |
| --- | --- | --- | --- |
| Spawn | `ptyprocess.PtyProcess.spawn` | `UnixPty.__init__` | `ptyprocess` imports `termios`/`fcntl`/`pty`; needs `pywinpty` (ConPTY). |
| Read | `loop.add_reader(fd)` + `os.read` on a non-blocking master fd | `Terminal.__init__`, `_on_readable` | ConPTY gives pipe handles, which `select` can't watch. uvicorn runs the Proactor loop on Windows, whose `add_reader` raises `NotImplementedError` anyway. |
| Write | `os.write` + `select` on `EAGAIN` (already on a worker thread) | `UnixPty.write` | Blocking pipe write is fine on that worker thread. |
| Resize | `setwinsize` | `UnixPty.resize` | `ResizePseudoConsole`, wrapped by pywinpty. |
| Busy | `os.tcgetpgrp(fd) != pid` when no OSC 133 | `Terminal.is_busy` | No process groups / controlling tty. |
| Cwd | `/proc/<pid>/cwd`, `libproc`, `lsof` | `UnixPty.cwd` | No supported API for another process's cwd. |
| Close | SIGHUP → SIGTERM → SIGKILL | `UnixPty.terminate` | No signals; children may outlive the shell. |
| Shell | `$SHELL -l` | `shellprobe.default_shell` | Already probes `pwsh` → `powershell` → `cmd`. No way to pick MSYS2/Git Bash. |

These smaller items don't block the port:

- `controller._shell_quote` quotes dropped paths for POSIX shells. PowerShell and cmd need their own quoting (in client mode the paths go to the remote Unix shell and are meaningless anyway).
- `auth.py` `chmod 0600` on the token is a no-op on Windows; the per-user profile ACL is the protection there. Fine, but say so in the docs.
- `os.replace` in `_atomic_write` can fail with `PermissionError` while antivirus or an indexer holds the target. It's already logged and the next save retries; check the log volume on a real machine.
- Freeze diagnostics (`SIGUSR1`/`SIGINFO`) are skipped where the signal doesn't exist. Nothing to do.

## Design

### 1. Move reading into the backend

This is the one structural change. It can land on macOS/Linux first, with no behavior change, and be tested there.

Today `Terminal` reads the fd itself. Replace `PtyBackend.fd` with a push interface:

```python
class PtyBackend(Protocol):
    def attach(self, loop: asyncio.AbstractEventLoop, on_data: Callable[[bytes], None]) -> None:
        """Start delivering output on the loop thread; b"" means EOF."""
    def detach(self) -> None: ...
    def foreground_busy(self) -> bool | None:
        """Kernel-level "a command is running" guess; None = can't tell."""
    # write / resize / is_alive / terminate / exit_code / cwd / pid as today
```

- `UnixPty.attach` keeps today's `add_reader` + `os.read` (the `BlockingIOError`/`EIO` handling moves with it). `foreground_busy` is today's `tcgetpgrp` check.
- `WindowsPty.attach` starts one daemon thread per terminal: blocking read, then `loop.call_soon_threadsafe(on_data, chunk)`. A thread per terminal is fine at our scale (tens of tabs). `detach` closes the pty so the blocked read returns.
- `Terminal._on_readable` becomes `_on_data(data)`; `is_busy` calls `self._pty.foreground_busy()` instead of `os.tcgetpgrp`.

Keep the "never block the loop" rule from `05-lessons-learned.md`: on Windows the only loop-thread work is the callback; reads happen on the reader thread.

Forcing the Selector loop on Windows (so `add_reader` exists) is not an option: `select()` on Windows only accepts sockets, and ConPTY output arrives on pipes.

### 2. `WindowsPty` on pywinpty

- Dependencies: `ptyprocess>=0.7; sys_platform != 'win32'` and `pywinpty>=2; sys_platform == 'win32'`. `spawn_pty` dispatches on `sys.platform`.
- Env: same `TERM`, `TERMINUX=1`, `TERM_PROGRAM=terminux`.
- **Bytes vs. str (verify in the spike):** terminux pipes bytes end to end (backlog, scrollback, websocket). If pywinpty's read returns `str`, encode it to UTF-8 at the boundary (ConPTY emits UTF-8); if write takes `str`, decode input with `errors="surrogateescape"` or similar. Check that a multibyte character split across two reads comes out intact. This is the likeliest source of subtle bugs.
- ConPTY rewrites the output stream (it renders its own buffer and re-emits it). Expect differences from Unix: some escape sequences are swallowed or reordered, and OSC sequences only pass through on recent Windows builds. Verify OSC 133, OSC 0/2 titles and OSC 8 links in the spike.

### 3. Busy signal

`foreground_busy` on Windows: "does the shell process have a child process?" via `CreateToolhelp32Snapshot` + `Process32First/Next` through `ctypes` (no new dependency). That's the same idea as `tcgetpgrp` and is cheap at 1 Hz. OSC 133 still wins when the shell reports it, as on Unix.

### 4. Cwd

The shell will have to report its cwd. Windows offers no supported API for reading another process's cwd. Reading the PEB through `NtQueryInformationProcess` is undocumented and breaks across bitness, so we skip it. Plan:

- Parse **OSC 7** (`file://host/path`) and **OSC 9;9** (`"C:\path"`, the Windows Terminal convention that oh-my-posh and Starship emit) in `_AttentionScanner`, and keep the last value on the `Terminal`.
- `Terminal.cwd()` prefers the reported value and falls back to `self._pty.cwd()`. This also helps on Unix, for shells inside SSH where the kernel cwd is the local `ssh` process.
- Ship a PowerShell prompt snippet in `guides/shell-integration.md` that emits OSC 133 and OSC 9;9.

**Existing bug to fix first (all platforms):** `_osc_should_fire` treats every `OSC 9;…` as a notification. `OSC 9;9` (cwd) and `OSC 9;4` (progress, emitted by winget, and by more and more tools on every platform) would turn the attention dot on at every prompt. Only plain `OSC 9;<message>` should fire; skip `9;1` through `9;12` (the ConEmu subcommands).

### 5. Closing a tab

pywinpty's terminate closes the pseudo console, which sends `CTRL_CLOSE_EVENT` to the console processes attached to it. Detached children (a `Start-Process`, a GUI app, a server started in the background) keep running. Plan:

1. Start with pywinpty's terminate and check in the spike which processes keep running.
2. If needed, put the shell in a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` right after spawn (`ctypes`, no pywin32), and close the job handle on `terminate`. It's the standard way to kill a whole process tree on Windows.

### 6. Shell choice

Keep the `pwsh` → `powershell` → `cmd` default. Add one setting for the shell command (decide where settings live first: a field in `UiPrefs` with a command-palette entry is the existing pattern). MSYS2 and Git Bash users point it at `C:\msys64\usr\bin\bash.exe --login -i`; they need `MSYSTEM` (e.g. `UCRT64`) in the env to get the right environment. Don't read `$SHELL` on Windows: inside MSYS2 it's a POSIX path (`/usr/bin/bash`).

### 7. Frontend

- `appMod` already treats non-Mac as Ctrl+Shift, which matches Windows Terminal. Nothing to do.
- Decide whether Ctrl+C copies when there's a selection and Ctrl+V pastes (Windows Terminal's default). Optional; Ctrl+Shift+C/V works already.

## Milestones

Each milestone can be released on its own.

0. **Client mode** (done). `--connect` from Windows works. Icon, links, data folder.
1. **Spike** (on a Windows machine, ~1 hour). A throwaway script that spawns `pwsh` through pywinpty and answers: read/write types (bytes or str); does a blocking read return promptly when the pty is closed; resize; exit code; which OSC sequences ConPTY passes through; which processes outlive terminate (start `Start-Process notepad` and a background `ping -t`, close, check Task Manager). Record the answers here.
2. **Reader refactor** (macOS/Linux, no behavior change). Section 1 above, plus the OSC 9 fix. The full test suite must stay green; this is where most of the risk lives and it's testable here.
3. **`WindowsPty`**. Sections 2, 3 and 5 (with the Job Object only if milestone 1 says so). Goal: open tabs, type, resize, close, restart a shell, scrollback persistence.
4. **Cwd + shell choice**. Sections 4 and 6, plus the PowerShell snippet.
5. **Tests, CI, docs, packaging.**
   - CI: a `windows-latest` job. Unit tests first; integration tests need a shell-agnostic helper (many hardcode `/bin/sh` and `stty size`): mark the POSIX-specific ones `skipif(sys.platform == "win32")` and add Windows twins for spawn/echo/resize/exit (`pwsh -NoProfile -Command`, `$Host.UI.RawUI.WindowSize`). Playwright e2e runs unchanged once a shell echoes.
   - Docs: installation (WebView2 ships with Windows 10/11; `uvx terminux` works as is), the "where state lives" table, and the FAQ/README "not yet" lines.
   - Packaging: a PyInstaller onedir build with `icon.ico` (`terminux.spec` currently assumes `.icns`), then decide whether to sign it. An installer can wait.

## Open questions

- Is a reader thread per terminal fine, or does one thread multiplexing with `WaitForMultipleObjects` matter? (Probably not below ~60 tabs.)
- Should cwd reporting via OSC 7/9;9 replace `lsof` on macOS too? It's faster and works over SSH, though it needs shell integration.
- Do we want a Windows CI runner on sourcehut, or GitHub Actions only?
