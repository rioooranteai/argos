from __future__ import annotations

import json
import logging

from app.core.observability.telemetry import spans
from app.core.observability.telemetry.context import bind_trace
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import NodeTrace
from app.engines.chat_engine.prompt_blocks import build_prompt, load_prompt
from app.tools.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_ROUTER_INSTRUCTIONS = load_prompt("router_agent.md")


def _record_decision(result: dict) -> None:
    """The router's decision becomes a trace tag + metadata, filterable in Langfuse."""
    fallback = any(t.status == "error" for t in result.get("node_traces", []))
    tags = [f"route:{result['route']}"] + (["route:fallback"] if fallback else [])
    bind_trace(tags=tags, route=result["route"], router_reasoning=result.get("router_reasoning"))


@traced_node(
    "routing", spans.CHAIN,
    inputs=lambda state: state["user_input"],
    outputs=lambda result: {"route": result["route"], "reasoning": result.get("router_reasoning")},
    error_is_warning=True,  # a failed router falls back to `both`; the chat still answers
    after=_record_decision,
)
async def router_node(state: dict, llm: BaseLLM) -> dict:
    # One message, fixed block order: HISTORY → INSTRUCTIONS → QUESTION → CURRENT_DATE.
    prompt = build_prompt(
        history=state.get("messages", []),
        instructions=_ROUTER_INSTRUCTIONS,
        question=state["user_input"],
    )

    clock = Stopwatch()
    try:
        raw = await llm.ainvoke(prompt=prompt, system=None)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)

        route = parsed.get("route", "none")
        reasoning = parsed.get("reasoning", "")

        if route not in ("sql", "vector", "both", "none"):
            route = "vector"

        trace = NodeTrace(node="router", status="ok", duration_ms=clock.ms())
        return {"route": route, "router_reasoning": reasoning, "node_traces": [trace]}

    except Exception:
        logger.exception("[router] Failed to pick a route; using the fallback route.")
        trace = NodeTrace(node="router", status="error", duration_ms=clock.ms(), code="ROUTER_FAILED")
        # Fallback route `both`: reading every source beats guessing one
        # (DESIGN_GROUP_C.md §3).
        return {
            "route": "both",
            "router_reasoning": "Fallback route because source selection failed.",
            "node_traces": [trace],
        }
