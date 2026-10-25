"""Auth token guarding the loopback (or tunneled) server.

The token gates every control/data request (technical spec §6). Two shapes
of token coexist:

- **Per-session** (default in desktop mode) — a fresh random
  ``abc-def-ghi``-style code generated at import time. Reset every run.
- **Persistent** (``--server`` / ``--no-window``) — same format but read
  from ``~/.config/terminux/server.token`` so the URL is stable across
  restarts. The format is intentionally short and human-readable so a
  user can dictate the URL or paste it from server stdout into a client.

The 9-letter code is roughly 43 bits of entropy — enough for loopback +
SSH-tunneled access, marginal for raw network exposure. ``check_auth``
therefore tracks failed attempts per source IP and locks an IP for
``LOCKOUT_SECONDS`` after ``MAX_FAILURES`` failures, frustrating online
brute-force regardless of the bind host.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import string
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.requests import HTTPConnection

log = logging.getLogger(__name__)


def client_ip(conn: HTTPConnection) -> str:
    """Peer IP of an HTTP request or WebSocket (both are HTTPConnections)."""
    return conn.client.host if conn.client is not None else "unknown"


_ALPHABET = string.ascii_lowercase
_GROUPS = 3
_GROUP_LEN = 3
TOKEN_RE = re.compile(
    rf"^[a-z]{{{_GROUP_LEN}}}(-[a-z]{{{_GROUP_LEN}}}){{{_GROUPS - 1}}}$"
)

MAX_FAILURES = 10
LOCKOUT_SECONDS = 60.0

# Loopback clients get a much looser limit: they all share one IP, so a
# single stale client (e.g. a browser tab from a previous session polling
# with the old token, ~1 failure every 2 s) must not lock out the desktop
# window. But a reverse proxy on the same host (Caddy, nginx, a tunnel
# client) makes every internet client look like loopback, so there is
# still a cap: 10 guesses a second can't search the token space.
LOOPBACK_MAX_FAILURES = 100
LOOPBACK_WINDOW_SECONDS = 10.0
_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1"})
# Bind addresses that make the server unreachable from the network, so a
# remote client needs a tunnel. Anything else (0.0.0.0, ::, a specific
# interface) is listening where other machines can knock.
LOOPBACK_BINDS = _LOOPBACK_IPS | {"localhost"}


def _new_token() -> str:
    """Generate a fresh ``abc-def-ghi``-style code."""
    return "-".join(
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN))
        for _ in range(_GROUPS)
    )


# Mutable so ``load_or_create_persistent_token`` can rotate it before the
# server starts. Reads of this value (in ``token_ok``) compare it as-is.
SESSION_TOKEN: str = _new_token()


def token_ok(supplied: str | None) -> bool:
    """Constant-time token comparison."""
    return supplied is not None and secrets.compare_digest(supplied, SESSION_TOKEN)


# Per-IP failed-attempt tracking for ``check_auth``. Keyed by client IP →
# list of monotonic timestamps within the rolling ``LOCKOUT_SECONDS``
# window. Guarded by ``_attempts_lock`` so concurrent route handlers (in
# the Starlette threadpool) can read/write safely.
_failed_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()

# An IP's entry is only purged when that IP comes back, so a wide scan of
# distinct source addresses would otherwise grow the dict forever. Past
# this size, every IP whose newest failure has aged out of the lockout
# window is dropped on the next recorded failure.
_MAX_TRACKED_IPS = 1024


def _purge_old(attempts: list[float], now: float, window: float) -> list[float]:
    cutoff = now - window
    return [ts for ts in attempts if ts > cutoff]


def check_auth(supplied: str | None, client_ip: str) -> bool:
    """Token check + per-IP rate limit.

    Returns ``False`` if the token is wrong OR the IP is currently locked
    out for too many recent failures. Successful auth clears the IP's
    failure history. Loopback IPs get a looser limit (see
    ``LOOPBACK_MAX_FAILURES``).
    """
    if client_ip in _LOOPBACK_IPS:
        max_failures, window = LOOPBACK_MAX_FAILURES, LOOPBACK_WINDOW_SECONDS
    else:
        max_failures, window = MAX_FAILURES, LOCKOUT_SECONDS
    now = time.monotonic()
    with _attempts_lock:
        attempts = _purge_old(_failed_attempts.get(client_ip, []), now, window)
        if len(attempts) >= max_failures:
            _failed_attempts[client_ip] = attempts
            return False
        ok = token_ok(supplied)
        if ok:
            _failed_attempts.pop(client_ip, None)
            return True
        attempts.append(now)
        _failed_attempts[client_ip] = attempts
        if len(_failed_attempts) > _MAX_TRACKED_IPS:
            cutoff = now - LOCKOUT_SECONDS
            for ip in [ip for ip, ts in _failed_attempts.items() if ts[-1] <= cutoff]:
                del _failed_attempts[ip]
        if len(attempts) == max_failures:
            log.warning(
                "auth rate-limit triggered for %s (%d failures in %ds)",
                client_ip,
                max_failures,
                int(window),
            )
        return False


def _reset_rate_limiter() -> None:
    """Test helper: clear all tracked failed attempts."""
    with _attempts_lock:
        _failed_attempts.clear()


def load_or_create_persistent_token(path: Path) -> str:
    """Read a persistent token from ``path``, or generate and write one.

    If the file exists and its content matches the expected format, use it
    as-is. Otherwise generate a fresh token, write the file (creating the
    parent directory) with mode 0600, and return the new value. The
    module-level ``SESSION_TOKEN`` is updated so subsequent ``token_ok``
    calls validate against the persisted value.
    """
    global SESSION_TOKEN  # noqa: PLW0603 — exposed mutable for the persisted-token path
    if path.is_file():
        # An unreadable file raises: silently replacing it would change the
        # user's stable URL. Undecodable bytes are just malformed content.
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if TOKEN_RE.match(text):
            SESSION_TOKEN = text
            return text
        log.warning("ignoring malformed persistent token at %s; regenerating", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = _new_token()
    # Created 0600, never readable by others even for an instant.
    path.unlink(missing_ok=True)  # a malformed file may have looser modes
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(new + "\n")
    SESSION_TOKEN = new
    return new
