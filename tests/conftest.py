"""Shared pytest fixtures and configuration.

Test Pyramid Structure:
- tests/a_unit/        - Unit tests (fast, isolated, no I/O)
- tests/b_integration/ - Integration tests (component interactions, file I/O)
- tests/c_e2e/         - End-to-end tests (full app/CLI workflows)

Run specific test types:
    uv run pytest -m unit              # Run only unit tests
    uv run pytest -m integration       # Run only integration tests
    uv run pytest -m e2e               # Run only e2e tests
    uv run pytest tests/a_unit/        # Run by directory
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    """Automatically apply markers based on test directory."""
    for item in items:
        # Get the path relative to tests/
        test_path = Path(item.fspath)
        parts = test_path.parts

        # Apply markers based on directory
        if "a_unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "b_integration" in parts:
            item.add_marker(pytest.mark.integration)
        elif "c_e2e" in parts:
            item.add_marker(pytest.mark.e2e)


# -----------------------------------------------------------------------------
# Shared Fixtures
# -----------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"

# A profile-free PowerShell whose prompt reports the cwd (OSC 9;9): on
# Windows that's the only way terminux learns it (no /proc, no libproc).
_PS_PROMPT = 'function prompt { "$([char]27)]9;9;$($PWD.ProviderPath)$([char]7)PS> " }'


@dataclass(frozen=True)
class PortableShell:
    """A fast shell for tests (no user profile), with portable commands.

    ``/bin/sh`` on Unix; ``pwsh`` (or Windows PowerShell) on Windows.
    Type commands with ``\r`` (Enter), which both accept.
    """

    argv: list[str]

    @property
    def is_powershell(self) -> bool:
        return Path(self.argv[0]).stem.lower() in {"pwsh", "powershell"}

    def exit_argv(self, code: int) -> list[str]:
        """A shell that exits at once with ``code``."""
        if self.is_powershell:
            return [self.argv[0], "-NoLogo", "-NoProfile", "-Command", f"exit {code}"]
        return [self.argv[0], "-c", f"exit {code}"]

    def size_command(self, marker: str) -> str:
        """Prints ``<marker> <rows> <cols>`` as the shell sees its tty."""
        if self.is_powershell:
            size = "$Host.UI.RawUI.WindowSize"
            return f'Write-Host "{marker} $({size}.Height) $({size}.Width)"'
        return f"echo {marker} $(stty size)"

    @property
    def exit_command(self) -> str:
        return "exit"


def _test_shell() -> PortableShell:
    if not IS_WINDOWS:
        return PortableShell(["/bin/sh"])
    exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
    return PortableShell([
        exe,
        "-NoLogo",
        "-NoProfile",
        "-NoExit",
        "-Command",
        _PS_PROMPT,
    ])


@pytest.fixture(scope="session")
def test_shell() -> PortableShell:
    return _test_shell()
