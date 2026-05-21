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

import platformdirs

from terminux.core.model import AppState

log = logging.getLogger(__name__)


def state_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("terminux"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "state.json"


# Hard cap so a runaway capture can't fill the disk. SerializeAddon output
# includes ANSI escapes, so a 5000-line scrollback can easily run past 1 MB.
SCROLLBACK_MAX_BYTES = 2 * 1024 * 1024

# Tab ids are server-generated uuid4 strings; this guards against any future
# path traversal via a malformed id.
_TAB_ID_OK = re.compile(r"^[A-Za-z0-9_-]+$")


def scrollback_dir(base: Path | None = None) -> Path:
    base = base or state_path().parent
    d = base / "scrollback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scrollback_file(tab_id: str, base: Path | None = None) -> Path | None:
    if not _TAB_ID_OK.match(tab_id):
        return None
    return scrollback_dir(base) / f"{tab_id}.ansi"


def save_scrollback(tab_id: str, content: str, base: Path | None = None) -> None:
    """Atomically persist a tab's serialized buffer, bounded to SCROLLBACK_MAX_BYTES.

    If the content exceeds the cap we keep only the tail (the most recent
    output) so the restored view reflects what was last on screen.
    """
    path = _scrollback_file(tab_id, base)
    if path is None:
        return
    data = content.encode("utf-8")
    if len(data) > SCROLLBACK_MAX_BYTES:
        data = data[-SCROLLBACK_MAX_BYTES:]
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".scrollback-",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(path)
    except OSError:
        log.exception("failed to persist scrollback for %s", tab_id)
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)


def load_scrollback(tab_id: str, base: Path | None = None) -> str | None:
    path = _scrollback_file(tab_id, base)
    if path is None:
        return None
    try:
        # Read in binary + decode by hand. ``Path.read_text(newline=None)``
        # enables universal-newlines mode and silently rewrites every
        # ``\r\n`` to ``\n`` — which strips the CR that SerializeAddon emits
        # between rows, and the replay then renders as a cumulative
        # LF-without-CR "staircase" of restored content.
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        log.warning("could not read scrollback for %s (%s)", tab_id, exc)
        return None


def delete_scrollback(tab_id: str, base: Path | None = None) -> None:
    path = _scrollback_file(tab_id, base)
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
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as exc:
        log.warning("could not load state from %s (%s); starting fresh", path, exc)
    return AppState.default()


def save_state(state: AppState, path: Path | None = None) -> None:
    """Write state atomically (temp file + os.replace)."""
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_json(), indent=2)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(path)
    except OSError:
        log.exception("failed to persist state to %s", path)
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
