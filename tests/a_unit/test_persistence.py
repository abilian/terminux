"""Unit tests for atomic JSON persistence."""

from __future__ import annotations

from pathlib import Path

from terminux.core import persistence
from terminux.core.model import AppState
from terminux.core.persistence import load_state, save_state, state_path


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


def test_save_handles_replace_oserror(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "state.json"

    def boom(self, _target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    save_state(AppState.default(), p)  # error is logged, not raised
    assert not p.exists()
    assert not list(tmp_path.glob(".state-*.tmp"))  # temp cleaned up
