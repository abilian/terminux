"""Atomic, versioned JSON persistence of structural state.

Live processes and scrollback are never persisted (functional spec §7):
a restored tab starts a fresh shell.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path

import platformdirs

from terminux.core.model import AppState

log = logging.getLogger(__name__)


def state_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("terminux"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "state.json"


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
