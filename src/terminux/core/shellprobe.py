"""Resolve the default shell and starting directory per OS."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def default_shell() -> list[str]:
    """Return the argv for a fresh interactive login shell."""
    if sys.platform == "win32":
        for candidate in ("pwsh.exe", "powershell.exe", "cmd.exe"):
            found = shutil.which(candidate)
            if found:
                return [found]
        return ["cmd.exe"]
    shell = os.environ.get("SHELL")
    if shell and Path(shell).exists():
        return [shell, "-l"]
    for candidate in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if Path(candidate).exists():
            return [candidate, "-l"]
    return ["/bin/sh"]


def default_cwd() -> str:
    """Starting directory for a new terminal (home, with cwd fallback)."""
    home = Path.home()
    if home.is_dir():
        return str(home)
    return str(Path.cwd())
