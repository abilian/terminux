"""Atomic, versioned JSON persistence of structural state.

The live shell is never persisted: a restored tab always starts a fresh
process. Each tab's visible/scrollback buffer is captured separately as
ANSI-replayable text (one file per tab in `scrollback/`) and replayed into
the new terminal on restart — see save_scrollback / load_scrollback.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import platformdirs

from terminux.core.model import AppState
from terminux.diagnostics import time_op

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """Per-user data folder. ``appauthor=False``: on Windows the default
    author doubles the name (``AppData\\Local\\terminux\\terminux``);
    other platforms ignore it."""
    return Path(platformdirs.user_data_dir("terminux", appauthor=False))


def state_path() -> Path:
    return data_dir() / "state.json"


# Hard cap so a runaway capture can't fill the disk. SerializeAddon output
# includes ANSI escapes, so a 5000-line scrollback can easily run past 1 MB.
SCROLLBACK_MAX_BYTES = 2 * 1024 * 1024

# Tab ids are server-generated uuid4 strings; this guards against any future
# path traversal via a malformed id.
_TAB_ID_OK = re.compile(r"^[A-Za-z0-9_-]+$")


def scrollback_dir() -> Path:
    return state_path().parent / "scrollback"


def _scrollback_file(tab_id: str) -> Path | None:
    if not _TAB_ID_OK.match(tab_id):
        return None
    return scrollback_dir() / f"{tab_id}.ansi"


def _atomic_write(path: Path, data: bytes, *, prefix: str, label: str) -> None:
    """Write ``data`` to ``path`` atomically (temp file + fsync + replace).

    Best-effort by contract: any ``OSError`` — creating the temp file on a
    full disk included — is logged and swallowed. The in-memory state stays
    authoritative, the previous file is left intact, and the next save
    retries; callers (request handlers, window shutdown) never see it.
    """
    tmp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)  # the only writer
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
        tmp_path = Path(tmp_name)
        _write_synced(fd, data)
        tmp_path.replace(path)
    except OSError:
        log.exception("failed to persist %s", label)
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def _write_synced(fd: int, data: bytes) -> None:
    """Write ``data`` through ``fd`` and fsync it before closing."""
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def save_scrollback(tab_id: str, content: str) -> None:
    """Atomically persist a tab's serialized buffer, bounded to SCROLLBACK_MAX_BYTES.

    If the content exceeds the cap we keep only the tail (the most recent
    output) so the restored view reflects what was last on screen.
    """
    path = _scrollback_file(tab_id)
    if path is None:
        return
    data = _trim_scrollback(content.encode("utf-8"))
    with time_op(f"save_scrollback[{tab_id[:8]} {len(data) // 1024}KB]"):
        _atomic_write(
            path, data, prefix=".scrollback-", label=f"scrollback for {tab_id}"
        )


def _trim_scrollback(data: bytes) -> bytes:
    """Cap at SCROLLBACK_MAX_BYTES, keeping the client's one-line JSON
    header (``{"v":2,…}``, without which the client discards the file) and
    the newest rows. The tail starts after a newline: a whole row, and
    never inside a multi-byte UTF-8 character."""
    if len(data) <= SCROLLBACK_MAX_BYTES:
        return data
    header = b""
    if data.startswith(b"{"):
        end = data.find(b"\n") + 1
        header, data = data[:end], data[end:]
    tail = data[len(data) - (SCROLLBACK_MAX_BYTES - len(header)) :]
    return header + tail[tail.find(b"\n") + 1 :]


def load_scrollback(tab_id: str) -> str | None:
    path = _scrollback_file(tab_id)
    if path is None:
        return None
    with time_op(f"load_scrollback[{tab_id[:8]}]"):
        try:
            # Read in binary + decode by hand. ``Path.read_text(newline=None)``
            # enables universal-newlines mode and silently rewrites every
            # ``\r\n`` to ``\n`` — which strips the CR that SerializeAddon
            # emits between rows, and the replay then renders as a cumulative
            # LF-without-CR "staircase" of restored content.
            # ``replace``: a file trimmed mid-character by an older version
            # still loads.
            return path.read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("could not read scrollback for %s (%s)", tab_id, exc)
            return None


def delete_scrollback(tab_id: str) -> None:
    path = _scrollback_file(tab_id)
    if path is None:
        return
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def load_state(path: Path | None = None) -> AppState:
    """Load persisted state, falling back to a sane default on any error."""
    path = path or state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AppState.from_json(raw)
    except FileNotFoundError:
        log.info("no persisted state at %s; starting fresh", path)
    except OSError as exc:
        log.warning("could not read state from %s (%s); starting fresh", path, exc)
    except (KeyError, TypeError, ValueError) as exc:  # JSONDecodeError included
        # The next save would overwrite it: set it aside so the workspaces
        # can still be recovered by hand.
        kept = path.with_name(path.name + ".corrupt")
        with contextlib.suppress(OSError):
            path.replace(kept)
        log.warning(
            "could not parse state in %s (%s); moved it to %s, starting fresh",
            path,
            exc,
            kept,
        )
    return AppState.default()


def save_state_json(payload: dict[str, Any], path: Path | None = None) -> None:
    """Write an already-serialized state snapshot atomically.

    Takes a snapshot rather than an ``AppState`` so callers can build it under a
    lock and run the disk write (fsync!) outside it — a lock held across
    fsync stalls anyone else waiting on it, including the event loop.
    """
    path = path or state_path()
    data = json.dumps(payload, indent=2).encode("utf-8")
    with time_op(f"save_state[{len(data) // 1024}KB]"):
        _atomic_write(path, data, prefix=".state-", label=f"state to {path}")
