"""One span per LangGraph node.

The node functions stay as they are; ``@traced_node`` wraps them, records what went in and
what came out, and reads the outcome from the ``NodeTrace`` the node already returns
(error code → ERROR, fallback → WARNING).
"""
from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.observability.telemetry import spans

NodeFn = Callable[..., Awaitable[dict]]


def traced_node(
    name: str,
    kind: str,
    inputs: Callable[[dict], Any],
    outputs: Callable[[dict], Any],
    *,
    error_is_warning: bool = False,
    after: Callable[[dict], None] | None = None,
) -> Callable[[NodeFn], NodeFn]:
    def decorate(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: dict, **deps: Any) -> dict:
            with spans.span(name, kind) as span:
                spans.set_input(span, inputs(state))
                result = await fn(state, **deps)
                spans.set_output(span, outputs(result))
                for node_trace in result.get("node_traces", []):
                    spans.set_metadata(span, status=node_trace.status, duration_ms=node_trace.duration_ms)
                    if node_trace.status == "error":
                        code = node_trace.code or "ERROR"
                        if error_is_warning:
                            spans.set_warning(span, code)
                        else:
                            spans.set_error(span, code)
                if after is not None:
                    after(result)
                return result

        return wrapper

    return decorate
