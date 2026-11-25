"""Log context per request / per job.

Known fields: ``user_id``, ``session_id`` (the conversation), ``notebook_id``,
``version_id``, ``stage``, ``message_id``. Their values go into every log line (see ``logs.setup``) and
into the ``llm_calls`` records.

Two ways to set them:

- ``bind_request(**fields)`` updates the current request's dict *in place*.
  Used by synchronous FastAPI dependencies (which run in a thread): a
  contextvar ``set`` in a thread is not visible to the endpoint, but changes to
  the same dict are.
- ``scoped(**fields)`` creates a new dict for a ``with`` block and then
  restores the previous one. Used by the document worker (each asyncio task has
  its own copy of the context).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def current() -> dict[str, Any]:
    """A copy of the context fields currently set."""
    ctx = _log_context.get()
    return dict(ctx) if ctx else {}


def get(name: str) -> Any:
    ctx = _log_context.get()
    return ctx.get(name) if ctx else None


def start_request() -> object:
    """A new dict for one HTTP request. Called by the request ID middleware."""
    return _log_context.set({})


def end_request(token: object) -> None:
    _log_context.reset(token)  # type: ignore[arg-type]


def bind_request(**fields: Any) -> None:
    """Set fields for the rest of this request (see the module docstring)."""
    ctx = _log_context.get()
    clean = {k: v for k, v in fields.items() if v is not None}
    if ctx is None:
        _log_context.set(clean)
    else:
        ctx.update(clean)


@contextmanager
def scoped(**fields: Any) -> Iterator[None]:
    """Fields apply only inside the ``with`` block."""
    merged = {**current(), **{k: v for k, v in fields.items() if v is not None}}
    token = _log_context.set(merged)
    try:
        yield
    finally:
        _log_context.reset(token)
