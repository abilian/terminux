"""Unit tests for atomic JSON persistence."""

from __future__ import annotations

import errno
import logging
from pathlib import Path

import pytest

from terminux.core import persistence
from terminux.core.model import AppState
from terminux.core.persistence import (
    SCROLLBACK_MAX_BYTES,
    delete_scrollback,
    load_scrollback,
    load_state,
    save_scrollback,
    save_state_json,
    state_path,
)


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch) -> None:
    """Scrollback files go next to the state file: put both in tmp_path."""
    monkeypatch.setattr(persistence, "state_path", lambda: tmp_path / "state.json")


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s = AppState.default()
    s.workspaces[0].name = "kept"
    save_state_json(s.to_json(), p)
    assert p.exists()
    assert not list(tmp_path.glob(".state-*.tmp"))  # no temp left behind
    loaded = load_state(p)
    assert loaded.workspaces[0].name == "kept"


def test_load_missing_returns_default(tmp_path: Path) -> None:
    s = load_state(tmp_path / "absent.json")
    assert len(s.workspaces) == 1


def test_load_corrupt_json_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    s = load_state(p)
    assert len(s.workspaces) == 1
    # Set aside, not left for the next save to overwrite.
    assert not p.exists()
    assert (tmp_path / "state.json.corrupt").read_text(encoding="utf-8") == "{not json"


def test_load_bad_structure_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text('{"workspaces": "nope", "tabs": 5}', encoding="utf-8")
    s = load_state(p)
    assert len(s.workspaces) == 1


def test_state_path_uses_platformdirs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        persistence.platformdirs,
        "user_data_dir",
        lambda _name, **_kw: str(tmp_path / "tnx"),
    )
    p = state_path()
    assert p == tmp_path / "tnx" / "state.json"
    assert not p.parent.exists()  # created by the first save, not here


def test_save_default_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        persistence.platformdirs,
        "user_data_dir",
        lambda _name, **_kw: str(tmp_path / "d"),
    )
    save_state_json(AppState.default().to_json())
    assert (tmp_path / "d" / "state.json").exists()


def test_scrollback_round_trip(tmp_path: Path, in_tmp: None) -> None:
    save_scrollback("t1", "hello\x1b[1mworld\x1b[0m")
    assert load_scrollback("t1") == "hello\x1b[1mworld\x1b[0m"
    # Atomic write left no .tmp file behind.
    assert not list((tmp_path / "scrollback").glob(".scrollback-*.tmp"))


def test_scrollback_preserves_crlf(tmp_path: Path, in_tmp: None) -> None:
    """Universal-newlines regression: Path.read_text() silently rewrites
    \\r\\n to \\n, which strips the CR SerializeAddon emits between rows
    and turns the replay into a staircase of LF-without-CR positioning.
    Bytes must round-trip verbatim."""
    raw = "row1\r\nrow2\r\nrow3"
    save_scrollback("t1", raw)
    assert load_scrollback("t1") == raw


def test_scrollback_missing_returns_none(in_tmp: None) -> None:
    assert load_scrollback("ghost") is None


def test_scrollback_delete(tmp_path: Path, in_tmp: None) -> None:
    save_scrollback("t1", "data")
    delete_scrollback("t1")
    assert load_scrollback("t1") is None
    # Delete on a non-existent id is a no-op (best-effort).
    delete_scrollback("ghost")


def test_scrollback_oversize_keeps_the_header_and_whole_newest_rows(
    in_tmp: None,
) -> None:
    header = '{"v":2,"cols":80,"rows":24}\n'
    row = "é" * 39 + "\r\n"  # multi-byte: a byte cut could split a character
    rows = [f"{i:06d}{row}" for i in range(SCROLLBACK_MAX_BYTES // len(row) + 50)]
    save_scrollback("t1", header + "".join(rows))
    got = load_scrollback("t1") or ""
    assert len(got.encode("utf-8")) <= SCROLLBACK_MAX_BYTES
    assert got.startswith(header)  # without it the client drops the file
    body = got[len(header) :]
    assert "\ufffd" not in body
    assert body.startswith(rows[len(rows) - body.count("\n")])  # a whole row
    assert body.endswith(rows[-1])


def test_scrollback_trimmed_mid_character_by_an_old_version_still_loads(
    tmp_path: Path, in_tmp: None
) -> None:
    (tmp_path / "scrollback").mkdir()
    (tmp_path / "scrollback" / "t1.ansi").write_bytes("é".encode()[1:] + b"ok")
    assert load_scrollback("t1") == "\ufffdok"


def test_scrollback_rejects_path_traversal(tmp_path: Path, in_tmp: None) -> None:
    save_scrollback("../escape", "nope")
    # Nothing leaks outside the scrollback dir.
    assert not list(tmp_path.glob("escape*"))
    assert not list((tmp_path / "scrollback").glob("*"))


def test_save_handles_replace_oserror(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "state.json"

    def boom(self, _target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    save_state_json(AppState.default().to_json(), p)  # error is logged, not raised
    assert not p.exists()
    assert not list(tmp_path.glob(".state-*.tmp"))  # temp cleaned up


def test_save_logs_instead_of_raising_when_the_temp_file_cannot_be_created(
    tmp_path: Path, in_tmp: None, monkeypatch, caplog
) -> None:
    """A full disk can fail the temp-file creation itself, before anything
    is written. That must take the same log-and-continue path as any other
    persist failure (it used to escape as a 500 from the request handler)."""
    p = tmp_path / "state.json"
    p.write_text("previous", encoding="utf-8")

    def disk_full(*_a, **_k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(persistence.tempfile, "mkstemp", disk_full)
    with caplog.at_level(logging.ERROR, logger=persistence.log.name):
        save_state_json(AppState.default().to_json(), p)  # must not raise
        save_scrollback("tab1", "content")  # same helper
    assert p.read_text(encoding="utf-8") == "previous"  # old file intact
    assert sum("failed to persist" in r.getMessage() for r in caplog.records) == 2


def test_data_dir_has_no_doubled_author_folder(monkeypatch) -> None:
    """platformdirs' default appauthor gives AppData\\Local\\terminux\\terminux
    on Windows; it must be turned off."""
    seen: dict[str, object] = {}

    def fake(name: str, **kw: object) -> str:
        seen.update(kw, name=name)
        return "/x"

    monkeypatch.setattr(persistence.platformdirs, "user_data_dir", fake)
    persistence.data_dir()
    assert seen == {"name": "terminux", "appauthor": False}


def test_last_used_at_survives_a_restart(tmp_path: Path) -> None:
    """Sort by Recent Activity works right after a restart because the
    time of the last keystroke in each workspace is saved with the state."""
    s = AppState.default()
    s.workspaces[0].last_used_at = 1_700_000_000
    p = tmp_path / "state.json"
    save_state_json(s.to_json(), p)
    assert load_state(p).workspaces[0].last_used_at == 1_700_000_000
