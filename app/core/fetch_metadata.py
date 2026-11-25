"""The API cannot be opened by URL in a browser.

Modern browsers always send Fetch Metadata headers (``Sec-Fetch-Mode``,
``Sec-Fetch-Dest``, ``Sec-Fetch-Site``), and a web page cannot forge them.

For ``/api/*`` and ``/health/ready``:

- Navigations (address bar, links, new tab) or loads as a document/iframe → 404.
- Calls from another site (``cross-site``/``same-site``) or with no origin (``none``) → 404.
- ``fetch()`` from the Argos page itself (``same-origin``) → on to the login check.
- No Fetch Metadata headers (curl, scripts, very old browsers) → on to the login check.
  When such a request uses the session cookie and changes data (POST/PUT/PATCH/DELETE),
  the ``Origin`` header must match the Argos origin (a second CSRF layer) → otherwise 403.

An empty 404 is used so that someone probing gets no hint that the endpoint
exists. Exception: the Google login flow really is a browser navigation.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_body
from app.core.observability.logs.request_id import get_request_id

logger = logging.getLogger(__name__)

PROTECTED_PREFIXES = ("/api/", "/health/ready")
EXEMPT_PATHS = frozenset({"/api/v1/auth/google/login", "/api/v1/auth/google/callback"})
_DOCUMENT_DESTS = frozenset({"document", "iframe", "frame", "embed", "object"})
_FOREIGN_SITES = frozenset({"cross-site", "same-site", "none"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _is_protected(path: str) -> bool:
    return path.startswith(PROTECTED_PREFIXES) and path not in EXEMPT_PATHS


class FetchMetadataMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str], cookie_name: str) -> None:
        self.app = app
        self._allowed_origins = {o.rstrip("/").lower() for o in allowed_origins}
        self._cookie_name = cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_protected(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        mode = headers.get("sec-fetch-mode")
        dest = headers.get("sec-fetch-dest")
        site = headers.get("sec-fetch-site")

        if mode == "navigate" or dest in _DOCUMENT_DESTS or site in _FOREIGN_SITES:
            logger.info(
                "API blocked (Fetch Metadata): %s %s mode=%s dest=%s site=%s",
                scope["method"], scope["path"], mode, dest, site,
            )
            await self._send(send, 404, b"", None)
            return

        if (
            site is None
            and scope["method"] in _UNSAFE_METHODS
            and self._uses_session_cookie(headers)
            and not self._origin_allowed(headers, scope)
        ):
            logger.warning("Origin rejected for %s %s: %s", scope["method"], scope["path"],
                           headers.get("origin"))
            body = error_body("ORIGIN_NOT_ALLOWED", "Request from an origin that is not allowed.",
                              get_request_id())
            await self._send(send, 403, json.dumps(body).encode(), "application/json")
            return

        await self.app(scope, receive, send)

    def _uses_session_cookie(self, headers: dict[str, str]) -> bool:
        cookie = headers.get("cookie", "")
        return any(
            part.strip().startswith(f"{self._cookie_name}=") for part in cookie.split(";")
        )

    def _origin_allowed(self, headers: dict[str, str], scope: Scope) -> bool:
        origin = (headers.get("origin") or "").rstrip("/").lower()
        if not origin:
            return False
        own = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}".lower()
        return origin == own or origin in self._allowed_origins

    @staticmethod
    async def _send(send: Send, status: int, body: bytes, content_type: str | None) -> None:
        headers = [(b"content-length", str(len(body)).encode())]
        if content_type:
            headers.append((b"content-type", content_type.encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
