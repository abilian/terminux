"""Unit tests for shell/cwd probing."""

from __future__ import annotations

from pathlib import Path

from terminux.core import shellprobe
from terminux.core.shellprobe import default_cwd, default_shell


def test_default_shell_uses_env_shell(monkeypatch) -> None:
    monkeypatch.setattr(shellprobe.sys, "platform", "darwin")
    monkeypatch.setenv("SHELL", "/bin/sh")
    assert default_shell() == ["/bin/sh", "-l"]


def test_default_shell_falls_back_when_no_env(monkeypatch) -> None:
    monkeypatch.setattr(shellprobe.sys, "platform", "linux")
    monkeypatch.delenv("SHELL", raising=False)
    argv = default_shell()
    assert argv[0] in ("/bin/zsh", "/bin/bash", "/bin/sh")


def test_default_shell_windows(monkeypatch) -> None:
    monkeypatch.setattr(shellprobe.sys, "platform", "win32")
    monkeypatch.setattr(shellprobe.shutil, "which", lambda _n: None)
    assert default_shell() == ["cmd.exe"]


def test_default_shell_windows_finds_pwsh(monkeypatch) -> None:
    monkeypatch.setattr(shellprobe.sys, "platform", "win32")
    monkeypatch.setattr(
        shellprobe.shutil,
        "which",
        lambda n: "C:/pwsh.exe" if n == "pwsh.exe" else None,
    )
    assert default_shell() == ["C:/pwsh.exe"]


def test_default_shell_env_set_but_missing_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(shellprobe.sys, "platform", "linux")
    monkeypatch.setenv("SHELL", "/no/such/shell")
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    assert default_shell() == ["/bin/sh"]  # final fallback (no candidate exists)


def test_default_cwd_is_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    assert default_cwd() == str(tmp_path)


def test_default_cwd_falls_back_to_cwd(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: missing))
    monkeypatch.setattr(Path, "cwd", classmethod(lambda _cls: tmp_path))
    assert default_cwd() == str(tmp_path)
