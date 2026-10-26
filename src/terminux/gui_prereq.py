"""Can this machine open terminux's window, and what to install if not.

pywebview installs from PyPI, then needs GTK and WebKit *from the system* on
Linux, which pip cannot provide. Without them it raises "You must have either
QT or GTK with Python extensions installed in order to use pywebview": true,
naming no package, and arriving as a traceback after an install that looked
fine. macOS gets its backend (pyobjc) as a wheel; Windows uses WebView2
through pythonnet, also wheels. Only Linux is checked.

There are two ways to fail and they need different answers. The packages can
be missing, or present and unreachable: PyGObject is not a wheel, it lives in
the distribution's site-packages, and an isolated environment (pipx, `uv
tool`, `uvx`, a plain venv) never sees it. ``pipx install
--system-site-packages`` works; `uv tool` and `uvx` have no such flag. So the
message asks the system interpreter before deciding what to say. Ported from
Libera Suite's ``libera/gui.py``, where each of these cases was met for real.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess  # noqa: S404 — argv form only, no shell: probes the system Python
import sys

# What pywebview's GTK backend requires (webview/platforms/gtk.py): Gtk and
# Gdk 3.0, then WebKit2 4.1 with Soup 3.0, else WebKit2 4.0 with Soup 2.4. The
# check below and the probe for the system Python read the same tables; when
# they disagreed, Libera told a box with PyGObject and no typelibs that its
# virtualenv was at fault.
NAMESPACES = (("Gtk", "3.0"), ("Gdk", "3.0"))
WEBKIT = (("4.1", "3.0"), ("4.0", "2.4"))

PACKAGES = {
    "debian": "sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1",
    "fedora": "sudo dnf install python3-gobject gtk3 webkit2gtk4.1",
    "arch": "sudo pacman -S python-gobject webkit2gtk-4.1",
    "suse": "sudo zypper install python3-gobject typelib-1_0-Gtk-3_0 "
    "typelib-1_0-WebKit2-4_1",
}

# ID and ID_LIKE in os-release, mapped to the family whose package names apply.
FAMILIES = {
    "debian": "debian",
    "ubuntu": "debian",
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "arch": "arch",
    "suse": "suse",
    "opensuse": "suse",
}

# For a distribution with none of the four package managers above: what to
# look for, in the names distributions actually use.
COMPONENTS = """  terminux needs three things your distribution packages:

    PyGObject             python3-gi, python-gobject, pygobject3
    the GTK 3 typelib     gir1.2-gtk-3.0, gtk3
    the WebKitGTK typelib gir1.2-webkit2-4.1, webkit2gtk4.1 (4.1, or 4.0)"""

NO_WINDOW = (
    "Or skip the window: `terminux --no-window` serves the same interface to\n"
    "any browser, at the URL it prints."
)


NO_DISPLAY = """\
terminux can't open its window: there is no display here (neither DISPLAY
nor WAYLAND_DISPLAY is set), as in an SSH session.

Run it without a window instead:

  terminux --no-window   serves it to a browser, at the URL it prints
  terminux --server -d   a background server, for `terminux --connect`
                         from a machine with a display (see Remote access)"""


def parse_family(os_release: str) -> str | None:
    """Which package manager's names to quote, from /etc/os-release: ID
    first, then ID_LIKE, which is what a derivative sets (Mint says
    ``ID=linuxmint``, ``ID_LIKE=ubuntu``)."""
    fields: dict[str, str] = {}
    for line in os_release.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip('"')
    for key in ("ID", "ID_LIKE"):
        for name in fields.get(key, "").split():
            if name in FAMILIES:
                return FAMILIES[name]
    return None


def format_install_hint(os_release: str) -> str:
    """The line to type, or what to ask for where there is no line."""
    family = parse_family(os_release)
    return f"  {PACKAGES[family]}" if family else COMPONENTS


def is_qt_available() -> bool:
    """Whether pywebview's Qt backend, its fallback for GTK (and its first
    choice under KDE), can load: ``qtpy`` and a Qt binding for it."""
    bindings = ("PyQt6", "PySide6", "PyQt5", "PySide2")
    return importlib.util.find_spec("qtpy") is not None and any(
        importlib.util.find_spec(b) is not None for b in bindings
    )


def is_gtk_available() -> bool:
    """Whether pywebview's GTK backend can start: ``gi`` imports (PyGObject)
    and the typelibs it asks for are installed."""
    try:
        import gi  # noqa: PLC0415  # ty: ignore[unresolved-import]
    except ImportError:
        return False
    try:
        for namespace, version in NAMESPACES:
            gi.require_version(namespace, version)
    except ValueError:
        return False
    for webkit, soup in WEBKIT:
        try:
            gi.require_version("WebKit2", webkit)
            gi.require_version("Soup", soup)
        except ValueError:
            continue
        return True
    return False


def make_probe_source() -> str:
    """``is_gtk_available``, written out for another interpreter: prints its
    "major.minor" and exits 0 when the backend could start there."""
    return (
        "import gi, sys\n"
        f"for ns, v in {NAMESPACES!r}:\n"
        "    gi.require_version(ns, v)\n"
        f"for webkit, soup in {WEBKIT!r}:\n"
        "    try:\n"
        "        gi.require_version('WebKit2', webkit)\n"
        "        gi.require_version('Soup', soup)\n"
        "        break\n"
        "    except ValueError:\n"
        "        continue\n"
        "else:\n"
        "    raise SystemExit(1)\n"
        "print('%d.%d' % sys.version_info[:2])\n"
    )


def _find_system_python_for_gtk() -> tuple[str, str] | None:
    """The distribution's interpreter that could open a window, and its
    "major.minor"; None where none could. Runs the whole check, not just
    ``import gi``. Only called on the way to refusing to start."""
    probe = make_probe_source()
    for interpreter in ("/usr/bin/python3", "/usr/bin/python"):
        if not pathlib.Path(interpreter).exists():
            continue
        try:
            done = subprocess.run(  # noqa: S603 — fixed interpreter, our own probe
                [interpreter, "-c", probe],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return interpreter, done.stdout.strip()
    return None


def detect_venv_kind(prefix: str | None = None) -> str:
    """How this copy was installed: "pipx", "uv-tool", "uvx" or "venv" (a
    checkout), from what each installer leaves behind."""
    root = pathlib.Path(prefix or sys.prefix)
    if (root / "pipx_metadata.json").exists() or "/pipx/venvs/" in str(root):
        return "pipx"
    if (root / "uv-receipt.toml").exists():
        return "uv-tool"
    if "/archive-v0/" in str(root):  # uvx: a throwaway env in uv's cache
        return "uvx"
    return "venv"


def _venv_fix() -> str:
    """The one line that lets this virtualenv see the system's PyGObject."""
    return (
        "  sed -i 's/^include-system-site-packages = false/"
        f"include-system-site-packages = true/' \\\n      {sys.prefix}/pyvenv.cfg"
    )


def _how_to_reach_it(interpreter: str, theirs: str) -> str:
    """The lines to type, for the way this copy was installed. The new
    environment is built on ``interpreter``, the system Python (version
    ``theirs``) that has PyGObject: a compiled extension reaches no other."""
    pipx = f"  pipx install --python {interpreter} --system-site-packages terminux"
    kind = detect_venv_kind()
    if kind == "pipx":
        return f"  pipx uninstall terminux\n{pipx}"
    if kind in {"uv-tool", "uvx"}:
        remove = "  uv tool uninstall terminux\n" if kind == "uv-tool" else ""
        return (
            "uv has no --system-site-packages for tools, so install it with pipx:\n\n"
            f"{remove}{pipx}"
        )
    if theirs != _ours():
        # UV_PYTHON is read ahead of .python-version, so `uv sync` keeps the
        # venv (and its pyvenv.cfg line) instead of rebuilding it on the
        # project's pinned version.
        return f"  export UV_PYTHON={interpreter}\n  uv sync\n{_venv_fix()}"
    note = "`uv sync` rewrites that file: a fresh sync needs it again."
    return f"{_venv_fix()}\n\n{note}"


def _ours() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def explain_why_no_window() -> str | None:
    """None when a window can be opened; otherwise what to tell the user."""
    if not sys.platform.startswith("linux"):
        return None
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        # Over SSH, say: GTK would only warn "cannot open display".
        return NO_DISPLAY
    if is_gtk_available() or is_qt_available():
        return None
    system = _find_system_python_for_gtk()
    if system:
        interpreter, theirs = system
        ours = _ours()
        why = (
            "terminux needs GTK and WebKit, which are installed on this machine,\n"
            "but this copy runs in an environment that cannot see them: PyGObject\n"
            "is not a wheel, so an isolated environment never finds it."
        )
        if theirs != ours:
            why = (
                f"terminux needs GTK and WebKit. This machine has them for Python "
                f"{theirs},\nand this copy runs on Python {ours}: PyGObject is "
                f"a compiled extension\nbuilt for one Python, so nothing on {ours} "
                "can reach it."
            )
        return f"{why}\n\n{_how_to_reach_it(interpreter, theirs)}\n\n{NO_WINDOW}"
    try:
        os_release = pathlib.Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        os_release = ""
    return (
        "terminux needs GTK and WebKit, which pip cannot install:\n\n"
        f"{format_install_hint(os_release)}\n\n"
        "Then reinstall it where it can see them:\n\n"
        "  pipx install --python /usr/bin/python3 --system-site-packages terminux\n\n"
        f"{NO_WINDOW}"
    )
