"""The part of the conversation each LLM sees.

The history comes from the database (``ConversationService``) on every message and stays whole
in ``state["messages"]``. Two nodes cut it down, each for one reader:

- ``router_history_node``: the last turns, each answer cut short. The router only picks the
  route and rewrites a follow-up ("and the G type?"), which refers to the latest turns.
- ``synth_history_node``: the newest whole messages within a token budget, for the answer.

Both keep the current question (the last message), even when it alone is over budget.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

from app.core.config import app_config
from app.core.observability.telemetry import spans
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import NodeTrace


def _summary(messages: list[AnyMessage]) -> dict:
    return {"messages": len(messages), "tokens": count_tokens_approximately(messages)}


def _trim(messages: list[AnyMessage], max_tokens: int, token_counter=count_tokens_approximately):
    """Newest messages within `max_tokens`, starting and ending on a user message."""
    trimmed = trim_messages(
        messages,
        strategy="last",
        token_counter=token_counter,
        max_tokens=max_tokens,
        start_on="human",
        end_on="human",
        include_system=False,
    )
    return trimmed or messages[-1:]


def _shorten_answer(message: AnyMessage, max_chars: int) -> AnyMessage:
    content = message.content
    if not isinstance(message, AIMessage) or not isinstance(content, str) or len(content) <= max_chars:
        return message
    return AIMessage(content=content[:max_chars].rstrip() + " …", id=message.id)


def router_history(
    messages: list[AnyMessage], turns: int, answer_chars: int, max_tokens: int
) -> list[AnyMessage]:
    """The last `turns` question/answer pairs + the current question, answers cut short."""
    recent = _trim(messages, max_tokens=2 * turns + 1, token_counter=len)
    shortened = [_shorten_answer(m, answer_chars) for m in recent]
    return _trim(shortened, max_tokens=max_tokens)


def synth_history(messages: list[AnyMessage], max_tokens: int) -> list[AnyMessage]:
    """The newest whole messages within `max_tokens`."""
    return _trim(messages, max_tokens=max_tokens)


def _trace(node: str, clock: Stopwatch, full: list[AnyMessage], kept: list[AnyMessage]) -> NodeTrace:
    return NodeTrace(
        node=node,
        status="ok",
        duration_ms=clock.ms(),
        details={"kept": _summary(kept), "dropped": len(full) - len(kept)},
    )


@traced_node(
    "router_history", spans.CHAIN,
    inputs=lambda state: _summary(state.get("messages", [])),
    outputs=lambda result: result["node_traces"][0].details,
)
async def router_history_node(state: dict) -> dict:
    clock = Stopwatch()
    messages = state.get("messages", [])
    kept = router_history(
        messages,
        turns=app_config.ROUTER_HISTORY_TURNS,
        answer_chars=app_config.ROUTER_HISTORY_ANSWER_CHARS,
        max_tokens=app_config.ROUTER_HISTORY_MAX_TOKENS,
    )
    return {"router_history": kept, "node_traces": [_trace("router_history", clock, messages, kept)]}


@traced_node(
    "synth_history", spans.CHAIN,
    inputs=lambda state: _summary(state.get("messages", [])),
    outputs=lambda result: result["node_traces"][0].details,
)
async def synth_history_node(state: dict) -> dict:
    clock = Stopwatch()
    messages = state.get("messages", [])
    kept = synth_history(messages, max_tokens=app_config.SYNTH_HISTORY_MAX_TOKENS)
    return {"synth_history": kept, "node_traces": [_trace("synth_history", clock, messages, kept)]}
