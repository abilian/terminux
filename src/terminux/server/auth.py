"""Per-session token guarding the loopback server.

A loopback HTTP server is reachable by any local process or browser tab, so
every control/data request must present the random session token (technical
spec §6).
"""

from __future__ import annotations

import secrets

SESSION_TOKEN: str = secrets.token_urlsafe(32)


def token_ok(supplied: str | None) -> bool:
    return supplied is not None and secrets.compare_digest(supplied, SESSION_TOKEN)
