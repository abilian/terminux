"""Open URLs in the OS default application — no shell, scheme-whitelisted.

Used by:

- The ``/api/open-url`` HTTP endpoint that the frontend hits when the user
  Cmd/Ctrl-clicks a link in a terminal (pywebview's WKWebView ignores JS
  ``window.open()``, so we route through Python).
- The native menu's ``Help → Documentation`` item.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess  # noqa: S404 — argv form only, no shell, opener path resolved via shutil.which
import sys
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Schemes safe to hand to the OS opener. ``file://``, ``javascript:``,
# ``data:`` etc. are deliberately omitted.
OPENABLE_SCHEMES = frozenset({"http", "https", "mailto"})


def open_url_in_default_app(url: str) -> bool:
    """Open ``url`` in the OS's default application.

    Returns True if a real opener was dispatched; False if the URL was
    rejected (bad scheme, malformed) or no opener exists on the platform.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in OPENABLE_SCHEMES:
        return False

    try:
        return _launch(url)
    except OSError:
        log.exception("failed to open url")
        return False


def _launch(url: str) -> bool:
    if sys.platform == "win32":
        # ShellExecute's "open" verb: no subprocess and no command line to
        # parse, so the URL stays opaque here too.
        os.startfile(url)  # noqa: S606 — scheme-whitelisted URL, no shell parsing
        return True
    if sys.platform == "darwin":
        opener = "open"
    elif sys.platform.startswith("linux"):
        opener = "xdg-open"
    else:
        return False
    if shutil.which(opener) is None:
        return False
    # No shell, no env munging — argv only, so the URL is opaque.
    subprocess.Popen(  # noqa: S603 — argv form, opener is a literal
        [opener, url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    return True
