"""Small helpers to create spans with the attributes Langfuse understands.

Only the OpenTelemetry API is used, so the code does not depend on Langfuse; the
``langfuse.*`` attribute names make the Langfuse UI show the right thing (they always win
over generic conventions), and ``gen_ai.*`` is filled where it applies so other OTLP
backends understand the data too. When telemetry is off, every call here is a cheap no-op.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from app.core.observability.telemetry.config import telemetry_config

# Langfuse observation types (langfuse.observation.type)
SPAN = "span"
GENERATION = "generation"
RETRIEVER = "retriever"
EMBEDDING = "embedding"
CHAIN = "chain"

_tracer = trace.get_tracer("argos")


def current_trace_id() -> str | None:
    """Hex trace ID of the active span (for logs and the message trace), or None."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


@contextmanager
def span(name: str, kind: str = SPAN, **attributes: Any) -> Iterator[Span]:
    """Start a child span of the current one; errors that escape mark it ERROR."""
    with _tracer.start_as_current_span(
        name, record_exception=False, set_status_on_exception=False
    ) as s:
        s.set_attribute("langfuse.observation.type", kind)
        set_attributes(s, **attributes)
        try:
            yield s
        except asyncio.CancelledError:
            set_warning(s, "CANCELLED")
            raise
        except BaseException as exc:
            if not getattr(s, "_argos_status_set", False):
                set_error(s, getattr(exc, "code", type(exc).__name__), exc=exc)
            raise


def set_attributes(s: Span, **attributes: Any) -> None:
    for key, value in attributes.items():
        if value is None:
            continue
        s.set_attribute(key, value if isinstance(value, (str, bool, int, float)) else str(value))


def set_metadata(s: Span, **metadata: Any) -> None:
    """Observation metadata (shown on this span in Langfuse)."""
    set_attributes(s, **{f"langfuse.observation.metadata.{k}": v for k, v in metadata.items()})


def _content(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    limit = telemetry_config.MAX_CONTENT_CHARS
    if len(text) > limit:
        text = text[:limit] + f"…[truncated {len(text) - limit} chars]"
    return text


def set_input(s: Span, value: Any) -> None:
    if telemetry_config.CAPTURE_CONTENT and value is not None and s.is_recording():
        s.set_attribute("langfuse.observation.input", _content(value))


def set_output(s: Span, value: Any) -> None:
    if telemetry_config.CAPTURE_CONTENT and value is not None and s.is_recording():
        s.set_attribute("langfuse.observation.output", _content(value))


def set_error(s: Span, code: str, message: str | None = None, exc: BaseException | None = None) -> None:
    """Mark the span failed with a stable error code (and the exception as an event)."""
    status = f"{code}: {message}" if message else code
    s.set_status(Status(StatusCode.ERROR, status))
    s.set_attribute("langfuse.observation.level", "ERROR")
    s.set_attribute("langfuse.observation.status_message", status)
    if exc is not None:
        s.record_exception(exc)
    s._argos_status_set = True  # type: ignore[attr-defined]


def set_warning(s: Span, message: str) -> None:
    s.set_attribute("langfuse.observation.level", "WARNING")
    s.set_attribute("langfuse.observation.status_message", message)
    s._argos_status_set = True  # type: ignore[attr-defined]
