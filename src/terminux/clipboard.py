"""Read the system clipboard where the webview can't (Windows).

WebView2 refuses the page's clipboard API without a permission flow
pywebview doesn't provide, so the Edit → Paste menu item reads the
clipboard here and hands the text to the page. Keyboard paste needs none
of this: the webview's own paste works.
"""

from __future__ import annotations

import ctypes
import sys

_CF_UNICODETEXT = 13


def read_text() -> str:
    """The clipboard's text, or "" when it holds none (or is busy)."""
    if sys.platform == "win32":
        return _windows_read_text()
    msg = "clipboard.read_text is only needed on Windows"
    raise NotImplementedError(msg)


if sys.platform == "win32":
    from ctypes import wintypes

    def _windows_read_text() -> str:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        if not user32.OpenClipboard(None):
            return ""  # another program holds it open
        try:
            handle = user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return ""
            data = kernel32.GlobalLock(handle)
            if not data:
                return ""
            try:
                return ctypes.wstring_at(data)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
