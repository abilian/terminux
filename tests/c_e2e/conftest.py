"""Playwright e2e fixtures: drive the served UI (no pywebview)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from terminux.server.auth import SESSION_TOKEN

if TYPE_CHECKING:
    from tests.conftest import LiveServer


@pytest.fixture
def app_url(server: LiveServer) -> str:
    return f"{server.url}/?t={SESSION_TOKEN}"
