"""Copies request/job context onto every span (DESIGN_GROUP_F.md §4.2).

Langfuse can only filter and aggregate by user, session, tags and metadata when they are on
every span, not just the root. Argos already carries that context in ``log_context`` (per
request / per job); this processor copies it when a span starts, together with the
trace-level tags/metadata collected by ``bind_trace()`` (e.g. the router's decision).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from app.core.observability.logs import context as log_context
from app.core.observability.logs.request_id import get_request_id

# log_context field → Langfuse attribute(s)
_IDENTITY = {"user_id": ("langfuse.user.id", "user.id"), "session_id": ("langfuse.session.id", "session.id")}
_METADATA_FIELDS = ("notebook_id", "version_id", "stage", "message_id")

# Trace-level attributes for the current trace: {"tags": set[str], "metadata": dict}.
# The dict is created by trace_scope() and mutated in place, so spans started later in
# other asyncio tasks (LangGraph nodes) still see what earlier spans added.
_trace_attrs: ContextVar[dict[str, Any] | None] = ContextVar("telemetry_trace_attrs", default=None)


@contextmanager
def trace_scope() -> Iterator[None]:
    """A fresh set of trace-level tags/metadata for one trace (chat message, document job)."""
    token = _trace_attrs.set({"tags": set(), "metadata": {}})
    try:
        yield
    finally:
        _trace_attrs.reset(token)


def bind_trace(*, tags: list[str] | tuple[str, ...] = (), **metadata: Any) -> None:
    """Add tags/metadata to the current trace; spans started from now on carry them."""
    attrs = _trace_attrs.get()
    if attrs is None:
        return
    attrs["tags"].update(tags)
    attrs["metadata"].update({k: v for k, v in metadata.items() if v is not None})


def trace_attributes() -> dict[str, Any]:
    """The current trace-level attributes as span attributes (used for the root span too)."""
    attrs = _trace_attrs.get()
    out: dict[str, Any] = {}
    if attrs is None:
        return out
    if attrs["tags"]:
        out["langfuse.trace.tags"] = sorted(attrs["tags"])
    for key, value in attrs["metadata"].items():
        out[f"langfuse.trace.metadata.{key}"] = _scalar(value)
    return out


def _scalar(value: Any) -> str | bool | int | float:
    return value if isinstance(value, (str, bool, int, float)) else str(value)


class ContextSpanProcessor(SpanProcessor):
    def __init__(self, environment: str) -> None:
        self._environment = environment

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        span.set_attribute("langfuse.environment", self._environment)
        ctx = log_context.current()
        for field, keys in _IDENTITY.items():
            if ctx.get(field):
                for key in keys:
                    span.set_attribute(key, str(ctx[field]))
        for field in _METADATA_FIELDS:
            if ctx.get(field) is not None:
                span.set_attribute(f"langfuse.trace.metadata.{field}", _scalar(ctx[field]))
        request_id = get_request_id()
        if request_id:
            span.set_attribute("langfuse.trace.metadata.request_id", request_id)
        for key, value in trace_attributes().items():
            span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:  # noqa: D401 — nothing to do on end
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
