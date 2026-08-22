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

# Loopback clients are exempt from the lockout: they all share one IP, so a
# single stale client (e.g. a browser tab from a previous session polling
# with the old token) would lock out the legitimate desktop window — a
# self-DoS. The lockout defends *network* exposure; a local attacker can
# read the token from the process listing anyway.
_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1"})


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


def _purge_old(attempts: list[float], now: float) -> list[float]:
    cutoff = now - LOCKOUT_SECONDS
    return [ts for ts in attempts if ts > cutoff]


def check_auth(supplied: str | None, client_ip: str) -> bool:
    """Token check + per-IP rate limit.

    Returns ``False`` if the token is wrong OR the IP is currently locked
    out for too many recent failures. Successful auth clears the IP's
    failure history. Loopback IPs skip the lockout entirely (see
    ``_LOOPBACK_IPS``).
    """
    if client_ip in _LOOPBACK_IPS:
        return token_ok(supplied)
    now = time.monotonic()
    with _attempts_lock:
        attempts = _purge_old(_failed_attempts.get(client_ip, []), now)
        if len(attempts) >= MAX_FAILURES:
            _failed_attempts[client_ip] = attempts
            return False
        ok = token_ok(supplied)
        if ok:
            _failed_attempts.pop(client_ip, None)
            return True
        attempts.append(now)
        _failed_attempts[client_ip] = attempts
        if len(attempts) == MAX_FAILURES:
            log.warning(
                "auth rate-limit triggered for %s (%d failures in %ds)",
                client_ip,
                MAX_FAILURES,
                int(LOCKOUT_SECONDS),
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
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if TOKEN_RE.match(text):
            SESSION_TOKEN = text
            return text
        log.warning("ignoring malformed persistent token at %s; regenerating", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = _new_token()
    path.write_text(new + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        log.warning("could not chmod 0600 the persistent token at %s", path)
    SESSION_TOKEN = new
    return new
