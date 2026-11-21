"""A request ID per request (DESIGN_GROUP_C.md §7).

- Taken from the ``X-Request-ID`` header (when safe) or newly generated.
- Stored in ``request.state`` and a contextvar, returned in a response header,
  and added to every log line through ``logging_setup.ContextFilter``.
- The middleware also opens a new log context per request (``log_context``).
"""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import log_context

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_var.get()


def request_id_from(request: Request) -> str | None:
    """Read the request ID from request.state (still there after the contextvar is reset)."""
    return getattr(request.state, "request_id", None) or get_request_id()


def _new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestIDMiddleware:
    """Pure ASGI middleware (does not wrap the body like BaseHTTPMiddleware)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name.lower() == REQUEST_ID_HEADER.lower().encode():
                incoming = value.decode("latin-1")
                break
        rid = incoming if incoming and _SAFE_ID.match(incoming) else _new_request_id()

        scope.setdefault("state", {})["request_id"] = rid
        token = _request_id_var.set(rid)
        ctx_token = log_context.start_request()

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:
                    headers.append(REQUEST_ID_HEADER, rid)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log_context.end_request(ctx_token)
            _request_id_var.reset(token)
