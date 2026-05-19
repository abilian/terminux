"""Unit tests for the session token guard."""

from __future__ import annotations

from terminux.server.auth import SESSION_TOKEN, token_ok


def test_token_ok_accepts_session_token() -> None:
    assert token_ok(SESSION_TOKEN) is True


def test_token_ok_rejects_wrong_and_none() -> None:
    assert token_ok("wrong") is False
    assert token_ok(None) is False
    assert token_ok("") is False
