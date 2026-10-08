"""End-to-end UI tests driving the served app with a real browser."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Page

UI = 15_000  # ms; shells (login → fish) can be slow to first prompt

# The browser runs on the host OS, so navigator.platform follows that and
# the frontend's appMod() picks Cmd on macOS, Ctrl+Shift on Linux — mirror
# that here so keyboard shortcuts work in both CI (Linux) and local dev.
APP_MOD = "Meta" if sys.platform == "darwin" else "Control+Shift"
# The command launcher is Cmd+Shift+P on macOS; on Linux that chord is
# the quick switcher, so the launcher lives on F1 (see keymap.ts).
CMD_PALETTE = "Meta+Shift+p" if sys.platform == "darwin" else "F1"


def test_app_loads_workspace_tab_and_terminal(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".ws-row")).to_have_count(1)
    expect(page.locator(".tab")).to_have_count(1)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)


def _wait_shell_ready(page: Page) -> None:
    """Wait until the terminal output is non-empty and stable (a prompt is
    drawn) — shell-agnostic, so keystrokes aren't sent into a not-yet-ready
    login shell (→ fish) and lost."""
    rows = page.locator(".xterm-rows")
    prev = ""
    for _ in range(40):  # up to ~16s
        page.wait_for_timeout(400)
        cur = rows.inner_text()
        if cur.strip() and cur == prev:
            return
        prev = cur


def _run_in_terminal(page: Page, type_text: str, expect_text: str) -> bool:
    rows = page.locator(".xterm-rows")
    for _ in range(15):
        _wait_shell_ready(page)
        page.locator(".xterm-helper-textarea").focus()
        page.keyboard.type(type_text)
        page.keyboard.press("Enter")
        try:
            expect(rows).to_contain_text(expect_text, timeout=2500)
        except AssertionError:
            page.wait_for_timeout(400)
        else:
            return True
    return False


def test_terminal_echo_roundtrip(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    assert _run_in_terminal(page, "echo e2e_OK_marker", "e2e_OK_marker")


def test_exited_tab_restarts_on_enter(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    rows = page.locator(".xterm-rows")
    # Ctrl+D (EOF) at a ready, empty prompt deterministically exits the
    # shell — more robust than typing a word the line editor may repaint.
    exited = False
    for _ in range(15):
        _wait_shell_ready(page)
        page.locator(".xterm-helper-textarea").focus()
        page.keyboard.press("Control+d")
        try:
            expect(rows).to_contain_text("process exited", timeout=2500)
        except AssertionError:
            page.wait_for_timeout(400)
        else:
            exited = True
            break
    assert exited, "shell did not exit on Ctrl+D"
    # Enter relaunches the shell in the same tab; assert a fresh shell drew
    # new output (a prompt) rather than typing into it again — the respawn
    # itself is deterministically covered by the backend tests.
    page.locator(".xterm-helper-textarea").focus()
    page.keyboard.press("Enter")
    expect(rows).not_to_contain_text("press Enter to restart", timeout=UI)


def test_new_and_close_tab(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".tab")).to_have_count(1)
    page.locator("#new-tab").click()
    expect(page.locator(".tab")).to_have_count(2)
    page.locator(".tab").last.locator(".x").click()
    expect(page.locator(".tab")).to_have_count(1)


def test_new_workspace(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".ws-row")).to_have_count(1)
    page.locator("#new-ws").click()
    expect(page.locator(".ws-row")).to_have_count(2)


def test_rename_survives_the_poll(page: Page, app_url: str) -> None:
    """A rename in progress must survive the 2 s state poll: the input,
    its text, and its focus all stay put while the sidebar re-renders
    underneath it. Enter commits and pins the name; Escape cancels."""
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    # Let the startup activation land first: ensureActiveTerminal focuses
    # the terminal a beat after .xterm appears, and a rename begun inside
    # that window is blurred (= committed) by that late focus. Same
    # behavior as the pre-island code; the terminal owning focus marks
    # the app as settled.
    expect(page.locator("textarea.xterm-helper-textarea")).to_be_focused(timeout=UI)
    page.locator(".ws-row.active .name").dblclick()
    box = page.locator(".ws-row .name-input")
    expect(box).to_be_visible()
    box.type("proj")
    page.wait_for_timeout(2500)  # let at least one poll re-render land
    expect(box).to_be_focused()
    expect(box).to_have_value("proj")
    box.type("ect-x")
    box.press("Enter")
    expect(page.locator(".ws-row.active .name")).to_have_text("project-x")
    # Escape cancels: the typed text is discarded, the pinned name stays.
    page.locator(".ws-row.active .name").dblclick()
    box = page.locator(".ws-row .name-input")
    expect(box).to_be_visible()
    box.type("zzz")
    box.press("Escape")
    expect(page.locator(".ws-row.active .name")).to_have_text("project-x")


# Note: sidebar-divider resize is intentionally not e2e-tested — synthetic
# pointer-drag is flaky in headless Chromium, and the resize clamping +
# persistence is covered deterministically by the /api/ui server test.


def test_palette_opens_filters_and_closes(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    pal = page.locator("#palette")
    expect(pal).to_be_hidden()
    page.keyboard.press(f"{APP_MOD}+p")
    expect(pal).to_be_visible()
    expect(pal.locator("input")).to_be_focused()
    # Lists the (single) workspace + its tab; typing filters the list.
    expect(pal.locator(".pal-row")).to_have_count(2)
    pal.locator("input").type("zzqqxx")  # matches nothing
    expect(pal.locator(".pal-row")).to_have_count(0)
    # Press Escape on the input itself: the close handler lives on the
    # input's keydown, and page.keyboard depends on focus — which a
    # background re-render can steal under full-suite load (flaked once).
    pal.locator("input").press("Escape")
    expect(pal).to_be_hidden()


def test_find_overlay_opens_and_closes(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    find = page.locator("#find")
    expect(find).to_be_hidden()
    page.keyboard.press(f"{APP_MOD}+f")
    expect(find).to_be_visible()
    expect(find.locator("input")).to_be_focused()
    page.keyboard.press("Escape")
    expect(find).to_be_hidden()


def test_sidebar_toggle_shortcut(page: Page, app_url: str) -> None:
    page.goto(app_url)
    sidebar = page.locator("#sidebar")
    expect(sidebar).to_be_visible()
    ws_name = page.locator(".ws-row.active .name").inner_text()
    # The window/tab title always carries the workspace name.
    assert page.title() == f"{ws_name} — terminux"
    # Sidebar visible → no chip (it would be redundant).
    chip = page.locator("#ws-chip")
    expect(chip).to_have_count(0)
    page.keyboard.press(f"{APP_MOD}+b")
    expect(sidebar).to_be_hidden()
    # Sidebar hidden → the chip stands in with the same workspace name.
    expect(chip).to_be_visible()
    expect(chip.locator(".name")).to_have_text(ws_name)
    page.keyboard.press(f"{APP_MOD}+b")
    expect(sidebar).to_be_visible()
    expect(chip).to_have_count(0)
    # Clicking the chip reopens the sidebar too.
    page.keyboard.press(f"{APP_MOD}+b")
    expect(chip).to_be_visible()
    chip.click()
    expect(sidebar).to_be_visible()
    expect(chip).to_have_count(0)
    # A page that loads with the collapsed pref already set shows the chip
    # from the start (applyLayout hides the sidebar after the first render).
    page.keyboard.press(f"{APP_MOD}+b")
    expect(chip).to_be_visible()
    page.reload()
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    expect(sidebar).to_be_hidden()
    expect(chip).to_be_visible()
    page.keyboard.press(f"{APP_MOD}+b")  # leave the sidebar visible for peers
    expect(sidebar).to_be_visible()


def test_terminal_reconnects_after_socket_drop(page: Page, app_url: str) -> None:
    """Severing the PTY websocket must not kill the tab: the frontend
    auto-reconnects, the backend replays its backlog, and typing works."""
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    assert _run_in_terminal(page, "echo before_drop_marker", "before_drop_marker")
    page.evaluate("[...window.__terminux.sessions.values()][0].ws.close()")
    assert _run_in_terminal(page, "echo after_drop_marker", "after_drop_marker")


def test_connect_info_command_shows_the_recipe(page: Page, app_url: str) -> None:
    """End to end: the command palette entry reaches the overlay, which
    asks the real backend and renders copyable commands. The test server
    is loopback-bound, so the SSH-tunnel branch is the one shown."""
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    overlay = page.locator("#connect-overlay")
    expect(overlay).to_be_hidden()

    page.keyboard.press(CMD_PALETTE)
    pal = page.locator("#cmdpalette")
    expect(pal).to_be_visible()
    pal.locator("input").type("remote connection")
    pal.locator("input").press("Enter")

    expect(overlay).to_be_visible()
    commands = overlay.locator(".connect-cmd code")
    expect(commands).to_have_count(2, timeout=UI)  # tunnel, then --connect
    expect(commands.first).to_contain_text("ssh -N -L 8443:localhost:")
    expect(commands.last).to_contain_text(
        "terminux --connect http://localhost:8443/?t="
    )
    # Per-session token here, so the "this address won't survive" warning shows.
    expect(overlay.locator(".connect-warn")).to_contain_text("until terminux restarts")

    page.keyboard.press("Escape")
    expect(overlay).to_be_hidden()


def test_each_window_gets_its_own_size_when_used(
    page: Page, app_url: str, monkeypatch
) -> None:
    """Two windows of different sizes on one terminal (desktop + --connect,
    the garbled-screen bug): typing in a window claims the terminal, so the
    shell sees that window's size. Each round prints a unique marker so an
    earlier round's output can't satisfy a later check."""
    monkeypatch.setattr("terminux.server.controller.default_shell", lambda: ["/bin/sh"])
    page.set_viewport_size({"width": 1200, "height": 800})
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    other = page.context.new_page()
    other.set_viewport_size({"width": 700, "height": 450})
    other.goto(app_url)
    expect(other.locator(".xterm")).to_be_visible(timeout=UI)

    def dims(p: Page) -> str:  # "rows cols", as `stty size` prints them
        return p.evaluate(
            "(() => { const s = [...window.__terminux.sessions.values()][0];"
            " return `${s.term.rows} ${s.term.cols}`; })()"
        )

    assert dims(page) != dims(other)  # otherwise the test proves nothing
    for n, p in enumerate((page, other, page), start=1):
        marker = f"M{n} {dims(p)}"
        assert _run_in_terminal(p, f"echo M{n} $(stty size)", marker), (
            f"round {n}: the shell did not see this window's size ({marker})"
        )
