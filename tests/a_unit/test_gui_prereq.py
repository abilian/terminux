"""What to tell someone whose install worked and whose window won't open.

On Linux pywebview needs GTK and WebKit from the system; its own error names
no package. Ported from Libera Suite, which met each of these cases.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from terminux import gui_prereq

OURS = f"{sys.version_info.major}.{sys.version_info.minor}"
# terminux requires 3.12+, so 3.9 is never the suite's own version.
ANOTHER_PYTHON = ("/usr/bin/python3", "3.9")


@pytest.mark.parametrize(
    ("os_release", "expected"),
    [
        ("ID=ubuntu\nID_LIKE=debian\n", "debian"),
        ("ID=linuxmint\nID_LIKE=ubuntu\n", "debian"),  # a derivative
        ('ID="fedora"\nVERSION_ID=42\n', "fedora"),
        ('ID=rocky\nID_LIKE="rhel centos fedora"\n', "fedora"),
        ("ID=arch\n", "arch"),
        ('ID=opensuse-tumbleweed\nID_LIKE="opensuse suse"\n', "suse"),
        ("", None),
        ("ID=plan9\n", None),
    ],
)
def test_the_distribution_decides_which_packages_to_name(os_release, expected):
    assert gui_prereq.parse_family(os_release) == expected


def test_a_known_distribution_gets_one_line():
    hint = gui_prereq.format_install_hint("ID=fedora\n")
    assert hint.strip().startswith("sudo dnf install")


def test_an_unknown_distribution_is_told_what_to_ask_for():
    """Four commands of which none exists is four wrong answers."""
    hint = gui_prereq.format_install_hint("ID=nixos\n")
    assert "install" not in hint.split("\n")[0]
    assert "PyGObject" in hint
    assert "typelib" in hint


def test_the_packages_are_the_ones_pywebview_asks_for():
    for line in gui_prereq.PACKAGES.values():
        assert "gtk" in line.lower()
        assert "webkit2" in line.lower().replace("-", "").replace("_", "")


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="the Linux case")
def test_nothing_to_say_where_the_backend_ships_with_pywebview():
    assert gui_prereq.explain_why_no_window() is None


@pytest.fixture
def linux_without_gtk(monkeypatch, tmp_path):
    """Linux with no GTK this environment can import, installed at the
    returned prefix (a checkout's venv until a test adds what pipx or uv
    leaves); the system Python has GTK, on our version, until a test says
    otherwise."""
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(gui_prereq, "is_gtk_available", lambda: False)
    monkeypatch.setattr(
        gui_prereq, "_find_system_python_for_gtk", lambda: ("/usr/bin/python3", OURS)
    )
    return tmp_path


def test_an_environment_that_cannot_see_the_system_packages_is_told_so(
    linux_without_gtk,
):
    (linux_without_gtk / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "--system-site-packages" in message
    assert "apt install" not in message, "they have the packages"
    assert "--no-window" in message, "the way in that needs no GTK"


def test_uvx_is_sent_to_pipx(monkeypatch, linux_without_gtk):
    """`uvx terminux` runs from uv's cache, and uv has no flag to see the
    system's PyGObject."""
    prefix = linux_without_gtk / "uv" / "archive-v0" / "abc"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "pipx install --python /usr/bin/python3 --system-site-packages" in message
    assert "uv tool uninstall" not in message, "uvx installed nothing"


def test_uv_tool_is_told_to_swap_for_pipx(linux_without_gtk):
    (linux_without_gtk / "uv-receipt.toml").write_text("", encoding="utf-8")
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "uv tool uninstall terminux" in message
    assert "pipx install" in message


def test_a_checkout_is_told_to_edit_its_pyvenv_cfg(linux_without_gtk):
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert f"{linux_without_gtk}/pyvenv.cfg" in message
    assert "pipx" not in message, "a checkout has nothing to uninstall"


def test_another_python_is_named(linux_without_gtk, monkeypatch):
    """No flag reaches a compiled extension built for another version."""
    (linux_without_gtk / "pipx_metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        gui_prereq, "_find_system_python_for_gtk", lambda: ANOTHER_PYTHON
    )
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "--python /usr/bin/python3" in message
    assert "3.9" in message
    assert OURS in message


def test_a_checkout_on_another_python_pins_uv_python(linux_without_gtk, monkeypatch):
    """`uv venv … && uv sync` undid itself: the sync rebuilt the venv on the
    pinned version and dropped the flag. UV_PYTHON keeps it."""
    monkeypatch.setattr(
        gui_prereq, "_find_system_python_for_gtk", lambda: ANOTHER_PYTHON
    )
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "UV_PYTHON=/usr/bin/python3" in message
    assert "uv venv" not in message


def test_missing_packages_are_named(linux_without_gtk, monkeypatch):
    monkeypatch.setattr(gui_prereq, "_find_system_python_for_gtk", lambda: None)
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "pip cannot install" in message
    assert "--system-site-packages" in message, "installing them isn't enough alone"


def test_the_probe_asks_the_same_question_as_the_check():
    """Run against this interpreter, the probe and the check must agree,
    whichever way the answer comes out."""
    done = subprocess.run(
        [sys.executable, "-c", gui_prereq.make_probe_source()],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (done.returncode == 0) is gui_prereq.is_gtk_available(), done.stderr[-400:]


@pytest.mark.parametrize(
    ("files", "path", "kind"),
    [
        ([], "", "venv"),
        (["pipx_metadata.json"], "", "pipx"),
        (["uv-receipt.toml"], "", "uv-tool"),
        ([], "uv/archive-v0/x", "uvx"),
    ],
)
def test_how_this_copy_was_installed(tmp_path, files, path, kind):
    root = tmp_path / path
    root.mkdir(parents=True, exist_ok=True)
    for name in files:
        (root / name).write_text("", encoding="utf-8")
    assert gui_prereq.detect_venv_kind(str(root)) == kind


def test_no_display_says_so_before_anything_about_gtk(monkeypatch):
    """Over SSH, GTK only warns "cannot open display"; the way forward is the
    window-less modes, whatever is installed."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(gui_prereq, "is_gtk_available", lambda: True)
    message = gui_prereq.explain_why_no_window()
    assert message is not None
    assert "no display" in message
    assert "--no-window" in message
    assert "--server" in message


def test_a_wayland_session_counts_as_a_display(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(gui_prereq, "is_gtk_available", lambda: True)
    assert gui_prereq.explain_why_no_window() is None
