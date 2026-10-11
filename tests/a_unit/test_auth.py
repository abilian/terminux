"""Unit tests for the session token guard."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

import pytest

from terminux.server import auth
from terminux.server.api import Api
from terminux.server.auth import (
    MAX_FAILURES,
    SESSION_TOKEN,
    TOKEN_RE,
    _new_token,
    _reset_rate_limiter,
    check_auth,
    load_or_create_persistent_token,
    token_ok,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def _fresh_rate_limiter() -> Iterator[None]:
    _reset_rate_limiter()
    yield
    _reset_rate_limiter()


pytestmark = pytest.mark.usefixtures("_fresh_rate_limiter")


@pytest.fixture
def isolated_token(monkeypatch) -> None:
    """Snapshot SESSION_TOKEN so a test can rotate it without polluting others.

    ``monkeypatch.setattr`` records the original value and restores it at
    test teardown, so the production module-level token is untouched after
    a test mutates it via ``load_or_create_persistent_token``.
    """
    monkeypatch.setattr(auth, "SESSION_TOKEN", auth.SESSION_TOKEN)


def test_token_ok_accepts_session_token() -> None:
    assert token_ok(SESSION_TOKEN) is True


def test_token_ok_rejects_wrong_and_none() -> None:
    assert token_ok("wrong") is False
    assert token_ok(None) is False
    assert token_ok("") is False


def test_session_token_matches_format() -> None:
    assert TOKEN_RE.match(SESSION_TOKEN), f"got {SESSION_TOKEN!r}"
    assert SESSION_TOKEN.count("-") == 2
    assert all(g.isalpha() and g.islower() for g in SESSION_TOKEN.split("-"))


def test_new_token_uses_meet_format() -> None:
    pattern = re.compile(r"^[a-z]{3}-[a-z]{3}-[a-z]{3}$")
    for _ in range(50):
        assert pattern.match(_new_token())


def test_check_auth_resets_failures_on_success() -> None:
    ip = "10.0.0.42"
    assert check_auth("wrong", ip) is False
    assert check_auth("wrong", ip) is False
    assert check_auth(SESSION_TOKEN, ip) is True
    # After a good auth the history is cleared: a full budget of failures
    # is available again before a lockout.
    for _ in range(MAX_FAILURES - 1):
        check_auth("wrong", ip)
    assert check_auth(SESSION_TOKEN, ip) is True


def test_check_auth_locks_after_max_failures() -> None:
    ip = "10.0.0.43"
    for _ in range(MAX_FAILURES):
        assert check_auth("wrong", ip) is False
    # The correct token is now refused — the IP is locked out.
    assert check_auth(SESSION_TOKEN, ip) is False


def test_check_auth_lockout_is_per_ip() -> None:
    """A lockout on one IP doesn't affect another."""
    bad = "10.0.0.44"
    good = "10.0.0.45"
    for _ in range(MAX_FAILURES):
        check_auth("wrong", bad)
    assert check_auth(SESSION_TOKEN, bad) is False
    assert check_auth(SESSION_TOKEN, good) is True


def test_check_auth_loopback_tolerates_a_stale_client() -> None:
    """Loopback clients all share one IP, so a stale client (old browser
    tab polling with a dead token) must not lock out the legitimate
    window: far more failures than the network limit still let the
    correct token through."""
    for ip in ("127.0.0.1", "::1"):
        for _ in range(MAX_FAILURES * 2):
            assert check_auth("wrong", ip) is False
        assert check_auth(SESSION_TOKEN, ip) is True


def test_check_auth_loopback_still_caps_guessing() -> None:
    """Behind a same-host reverse proxy every client is loopback, so a
    burst of guesses past the loopback limit locks it out too."""
    for _ in range(auth.LOOPBACK_MAX_FAILURES):
        check_auth("wrong", "127.0.0.1")
    assert check_auth(SESSION_TOKEN, "127.0.0.1") is False


def test_check_auth_failures_age_out(monkeypatch) -> None:
    """Failures older than LOCKOUT_SECONDS are discarded on the next check."""
    ip = "10.0.0.46"
    now = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    for _ in range(MAX_FAILURES):
        check_auth("wrong", ip)
    assert check_auth(SESSION_TOKEN, ip) is False  # locked
    now[0] += auth.LOCKOUT_SECONDS + 1
    assert check_auth(SESSION_TOKEN, ip) is True  # cleared


def test_check_auth_sweeps_stale_ips_past_cap(monkeypatch) -> None:
    """The tracked-IP table is bounded: entries are normally purged only when
    their own IP returns, so past the cap a failure sweeps out every IP whose
    newest failure aged beyond the lockout window."""
    now = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(auth, "_MAX_TRACKED_IPS", 3)
    for i in range(4):
        check_auth("wrong", f"10.0.1.{i}")
    assert len(auth._failed_attempts) == 4  # all still within the window
    now[0] += auth.LOCKOUT_SECONDS + 1
    check_auth("wrong", "10.0.2.99")  # pushes past the cap → sweep
    assert set(auth._failed_attempts) == {"10.0.2.99"}


def test_persistent_token_generates_and_writes(
    tmp_path: Path, isolated_token: None
) -> None:
    target = tmp_path / "nested" / "server.token"
    assert not target.exists()
    token = load_or_create_persistent_token(target)
    assert TOKEN_RE.match(token)
    assert target.read_text(encoding="utf-8").strip() == token
    assert token == auth.SESSION_TOKEN  # module-level was updated
    # On Windows chmod only toggles read-only; the per-user profile's ACL
    # is what protects the token there.
    if sys.platform != "win32":
        assert (target.stat().st_mode & 0o777) == 0o600


def test_persistent_token_reuses_existing(tmp_path: Path, isolated_token: None) -> None:
    target = tmp_path / "server.token"
    existing = "xyz-abc-def"
    target.write_text(existing + "\n", encoding="utf-8")
    token = load_or_create_persistent_token(target)
    assert token == existing
    assert existing == auth.SESSION_TOKEN


def test_persistent_token_replaces_malformed(
    tmp_path: Path, isolated_token: None
) -> None:
    malformed = "not-a-valid-token-at-all"
    target = tmp_path / "server.token"
    target.write_text(malformed + "\n", encoding="utf-8")
    token = load_or_create_persistent_token(target)
    assert TOKEN_RE.match(token)
    assert token != malformed


def test_page_embeds_the_persistent_token(tmp_path: Path, isolated_token: None) -> None:
    """``--server`` swaps in the persistent token after the API module is
    imported; the page must hand the browser that one, not the import-time
    session token, or every API call is a 403."""
    token = load_or_create_persistent_token(tmp_path / "server.token")
    html = bytes(Api.index(None).body).decode()  # type: ignore[arg-type]
    assert f'"{token}"' in html
