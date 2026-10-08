# Developing

## Setup

```sh
uv sync
make frontend        # build TS/Vite UI → src/terminux/web/static
```

## Common tasks

```sh
make frontend        # build the frontend (committed to src/terminux/web/static)
make frontend-dev    # live Vite dev server, proxying to a running backend
make frontend-test   # vitest unit tests (pure TS logic, no browser)
make test            # vitest, then pytest: unit, integration, e2e
make lint            # ruff + ty + pyrefly + mypy
make format          # ruff (Python) + prettier (frontend)
make test-cov        # pytest with HTML coverage report
```

For a live frontend loop: run `uv run terminux --no-window` in one terminal,
`make frontend-dev` in another. The Vite dev server proxies API/WS calls to the
running backend.

## Testing tiers

The pytest suite has three tiers, selectable by marker:

- **`unit`**: fast, isolated.
- **`integration`**: component interaction.
- **`e2e`**: drives the served UI with a real browser (Playwright, no
  pywebview).

The e2e tier needs the Playwright browser once:

```sh
uv run playwright install chromium
```

Frontend logic is covered separately by vitest (`make frontend-test`), which
`make test` runs first.

## Type checking

`make lint` runs **four** type checkers (`ty`, `pyrefly`, `mypy`) plus `ruff`.
mypy is in `strict` mode. The frontend has its own check:

```sh
cd frontend && npm run typecheck   # tsc
```

## Documentation

Docs are written in Markdown under `docs/src/` and built with
[Zensical](https://zensical.org/). Configuration lives in
`docs/zensical.toml`.

```sh
make docs-serve    # live preview with rebuild-on-save (http://127.0.0.1:8000)
make docs          # static site → docs/site/
```

To add a page, create it under the matching section directory in
`docs/src/` (`getting-started/`, `guides/`, `developers/`, or the root
for Home-tab pages) and add it to the `nav` array in `docs/zensical.toml`.

## Debugging knobs

### `--debug` and `--trace`

Every log line starts with a full date and time, even without flags, so a log from a long-running instance can be matched against what happened when. Two CLI flags raise the noise level when something goes wrong:

| Flag | What it does |
| --- | --- |
| `--debug` | `terminux.*` loggers at `DEBUG`, uvicorn `INFO` with access logs, timestamps down to the millisecond. Slow-I/O warnings (see below) are surfaced. |
| `--trace` | Everything `--debug` enables plus root logger at `DEBUG`: every `save_state`, `save_scrollback`, `load_scrollback`, and cwd lookup logs its individual duration. Very chatty; use only when actively chasing a freeze. |

```sh
uv run terminux --debug                  # daily-driver verbose
uv run terminux --debug 2>/tmp/term.log  # also redirect to a file you can grep
uv run terminux --trace 2>/tmp/term.log  # extreme mode for a known-reproducer
```

### Slow-I/O warnings

Every disk-touching call on the server is wrapped in a `time_op(name)`
context manager (see `src/terminux/diagnostics.py`). Operations slower
than **200 ms** log at `WARNING` regardless of the log level, so a slow
APFS volume, a wedged network mount, or a busy disk shows up as
`slow save_state[12KB]: 1340ms` before it escalates into a hang.

Wrapped sites:

- `save_state` and `save_scrollback` (both end in `os.fsync`)
- `load_scrollback` (sync file read up to 2 MB)
- `_libproc_cwd` and the `_lsof_cwd` fallback on macOS

### Event-loop watchdog

A daemon thread reads a heartbeat the asyncio loop is expected to bump
twice a second. If the loop falls more than **3 s** behind, the watchdog
logs at `WARNING` and **automatically calls
`faulthandler.dump_traceback(all_threads=True)` to stderr**: the same
per-thread Python stack dump you'd get from `py-spy dump`. The dump
includes whichever syscall the offending thread is parked in (`fsync`,
`subprocess.communicate`, `os.write`, …), which is the exact evidence
needed to find the root cause. It re-warns every 10 s while the stall
persists.

A stale heartbeat has a second, harmless cause: the whole process getting
no CPU (heavy swapping, a debugger, or macOS App Nap, which terminux opts
out of while its window is open). The watchdog tells the two apart by its
own lateness: when its 1 s sleep overruns by more than 3 s, every thread
was frozen. It then logs a single `INFO` line (`process got no CPU for
…s`) with no stack dump, and gives the resumed loop a fresh 3 s before
blaming it.

The watchdog is started automatically by `terminux.app.main()`; no flag
is required.

### Manual stack dump

If you suspect a hang but the watchdog hasn't fired yet, send the process
a signal yourself for the same dump on demand:

```sh
# macOS — SIGINFO is what Ctrl-T sends in a normal foreground terminal
kill -INFO <pid>

# Linux
kill -USR1 <pid>
```

`<pid>` comes from `ps aux | grep terminux | grep -v grep`. The dump
lands on the same stderr stream as the watchdog's output.

### `TERMINUX_PTY_LOG`

When set in the environment, every PTY read is appended to `<path>` as a
one-line trace: `<epoch.ms> <terminal-id-prefix> <byte_count> <repr of
first 120 bytes>`. Use it to characterize what an "idle" TUI actually
emits when you suspect a sidebar dot is reacting to noise. It is off by
default and leaves no trace on disk in normal runs.

```sh
rm -f /tmp/pty.log
TERMINUX_PTY_LOG=/tmp/pty.log uv run terminux
# reproduce the scenario
tail -n 50 /tmp/pty.log
```
