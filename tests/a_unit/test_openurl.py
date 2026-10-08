"""``open_url_in_default_app`` platform dispatch."""

from __future__ import annotations

from terminux import openurl


def test_windows_opens_urls_through_the_shell(monkeypatch) -> None:
    """Link clicks reach the default browser on Windows (a --connect client
    there has no other way to open them)."""
    opened: list[str] = []
    monkeypatch.setattr(openurl.sys, "platform", "win32")
    monkeypatch.setattr(openurl.os, "startfile", opened.append, raising=False)
    assert openurl.open_url_in_default_app("https://example.com/x")
    assert not openurl.open_url_in_default_app("file:///C:/Windows/notepad.exe")
    assert opened == ["https://example.com/x"]
