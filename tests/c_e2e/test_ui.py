"""End-to-end UI tests driving the served app with a real browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

if TYPE_CHECKING:
    from playwright.sync_api import Page

UI = 15_000  # ms; shells (login → fish) can be slow to first prompt


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


# Note: sidebar-divider resize is intentionally not e2e-tested — synthetic
# pointer-drag is flaky in headless Chromium, and the resize clamping +
# persistence is covered deterministically by the /api/ui server test.


def test_palette_opens_filters_and_closes(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    pal = page.locator("#palette")
    expect(pal).to_be_hidden()
    page.keyboard.press("Control+p")
    expect(pal).to_be_visible()
    expect(pal.locator("input")).to_be_focused()
    # Lists the (single) workspace + its tab; typing filters the list.
    expect(pal.locator(".pal-row")).to_have_count(2)
    pal.locator("input").type("zzqqxx")  # matches nothing
    expect(pal.locator(".pal-row")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(pal).to_be_hidden()


def test_find_overlay_opens_and_closes(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.locator(".xterm")).to_be_visible(timeout=UI)
    find = page.locator("#find")
    expect(find).to_be_hidden()
    page.keyboard.press("Control+f")
    expect(find).to_be_visible()
    expect(find.locator("input")).to_be_focused()
    page.keyboard.press("Escape")
    expect(find).to_be_hidden()


def test_sidebar_toggle_shortcut(page: Page, app_url: str) -> None:
    page.goto(app_url)
    sidebar = page.locator("#sidebar")
    expect(sidebar).to_be_visible()
    page.keyboard.press("Control+b")
    expect(sidebar).to_be_hidden()
    page.keyboard.press("Control+b")
    expect(sidebar).to_be_visible()
