"""Unit tests for atomic JSON persistence."""

from __future__ import annotations

from pathlib import Path

from terminux.core import persistence
from terminux.core.model import AppState
from terminux.core.persistence import (
    SCROLLBACK_MAX_BYTES,
    delete_scrollback,
    load_scrollback,
    load_state,
    save_scrollback,
    save_state,
    state_path,
)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s = AppState.default()
    s.workspaces[0].name = "kept"
    save_state(s, p)
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


def test_load_bad_structure_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text('{"workspaces": "nope", "tabs": 5}', encoding="utf-8")
    s = load_state(p)
    assert len(s.workspaces) == 1


def test_state_path_uses_platformdirs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        persistence.platformdirs,
        "user_data_dir",
        lambda _name: str(tmp_path / "tnx"),
    )
    p = state_path()
    assert p == tmp_path / "tnx" / "state.json"
    assert p.parent.is_dir()  # directory created


def test_save_default_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        persistence.platformdirs,
        "user_data_dir",
        lambda _name: str(tmp_path / "d"),
    )
    save_state(AppState.default())
    assert (tmp_path / "d" / "state.json").exists()


def test_scrollback_round_trip(tmp_path: Path) -> None:
    save_scrollback("t1", "hello\x1b[1mworld\x1b[0m", base=tmp_path)
    assert load_scrollback("t1", base=tmp_path) == "hello\x1b[1mworld\x1b[0m"
    # Atomic write left no .tmp file behind.
    assert not list((tmp_path / "scrollback").glob(".scrollback-*.tmp"))


def test_scrollback_preserves_crlf(tmp_path: Path) -> None:
    """Universal-newlines regression: Path.read_text() silently rewrites
    \\r\\n to \\n, which strips the CR SerializeAddon emits between rows
    and turns the replay into a staircase of LF-without-CR positioning.
    Bytes must round-trip verbatim."""
    raw = "row1\r\nrow2\r\nrow3"
    save_scrollback("t1", raw, base=tmp_path)
    assert load_scrollback("t1", base=tmp_path) == raw


def test_scrollback_missing_returns_none(tmp_path: Path) -> None:
    assert load_scrollback("ghost", base=tmp_path) is None


def test_scrollback_delete(tmp_path: Path) -> None:
    save_scrollback("t1", "data", base=tmp_path)
    delete_scrollback("t1", base=tmp_path)
    assert load_scrollback("t1", base=tmp_path) is None
    # Delete on a non-existent id is a no-op (best-effort).
    delete_scrollback("ghost", base=tmp_path)


def test_scrollback_oversize_is_tail_trimmed(tmp_path: Path) -> None:
    payload = "X" * (SCROLLBACK_MAX_BYTES + 1024)
    save_scrollback("t1", payload, base=tmp_path)
    got = load_scrollback("t1", base=tmp_path) or ""
    assert len(got.encode("utf-8")) == SCROLLBACK_MAX_BYTES
    # Tail-trimming keeps the most recent output.
    assert got.endswith("X")


def test_scrollback_rejects_path_traversal(tmp_path: Path) -> None:
    save_scrollback("../escape", "nope", base=tmp_path)
    # Nothing leaks outside the scrollback dir.
    assert not list(tmp_path.glob("escape*"))
    assert not list((tmp_path / "scrollback").glob("*"))


def test_save_handles_replace_oserror(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "state.json"

    def boom(self, _target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    save_state(AppState.default(), p)  # error is logged, not raised
    assert not p.exists()
    assert not list(tmp_path.glob(".state-*.tmp"))  # temp cleaned up
