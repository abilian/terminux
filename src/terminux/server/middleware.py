"""HTTP auth gate + hardening headers (§6).

Every HTTP route is token-guarded here, fail-closed — a new route can't
forget its auth check. Only the content-hashed static assets are public
(they contain no secrets and are needed before any JS runs). The PTY
WebSocket route never passes through this middleware (Starlette's
``BaseHTTPMiddleware`` sees HTTP only) and does its own ``check_auth``.

A loopback-only, token-guarded server doesn't strictly need CSP for
security — there's no remote origin to mix with — but pinning script
sources and blocking framing/navigation is cheap defence in depth and
catches accidental misconfigurations early.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from terminux.server.auth import check_auth, client_ip

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

# Paths served without a token: the immutable, content-hashed Vite bundle.
# ``/`` is NOT public — its response embeds the session token.
_PUBLIC_PREFIXES = ("/assets/",)


# Restrictive CSP: only same-origin bundled assets and the same-origin
# WebSocket; block remote origins, framing, and navigation away.
# 'unsafe-eval' is required by the pywebview runtime (it drives the webview
# via evaluate_js / injected code); the real protection here — no remote
# origins, no framing — is unaffected on a loopback, token-guarded server.
_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Token-gate every HTTP route and attach CSP/hardening headers."""

    async def dispatch(  # noqa: PLR6301 (BaseHTTPMiddleware override must be a method)
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if not path.startswith(_PUBLIC_PREFIXES) and not check_auth(
            request.query_params.get("t"), client_ip(request)
        ):
            response: Response = JSONResponse({"error": "forbidden"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
