"""Trim the conversation to a token budget before the router.

The history comes from the database (``ConversationService``) on every message; this node keeps
only the most recent part that fits ``CHAT_HISTORY_MAX_TOKENS``, so the router and the
synthesizer both read the same trimmed ``messages``. Nothing is deleted from the database.
"""
from __future__ import annotations

from langchain_core.messages import AnyMessage, RemoveMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from app.core.config import app_config
from app.core.observability.telemetry import spans
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import NodeTrace


def _summary(messages: list[AnyMessage]) -> dict:
    return {"messages": len(messages), "tokens": count_tokens_approximately(messages)}


def trim_history(messages: list[AnyMessage], max_tokens: int) -> list[AnyMessage]:
    """The newest messages that fit `max_tokens`, starting and ending on a user message.

    The current question (the last message) is always kept, even when it alone is over budget.
    """
    trimmed = trim_messages(
        messages,
        strategy="last",
        token_counter=count_tokens_approximately,
        max_tokens=max_tokens,
        start_on="human",
        end_on="human",
        include_system=False,
    )
    return trimmed or messages[-1:]


@traced_node(
    "history_trim", spans.CHAIN,
    inputs=lambda state: _summary(state.get("messages", [])),
    outputs=lambda result: result["node_traces"][0].details,
)
async def history_trimmer_node(state: dict) -> dict:
    clock = Stopwatch()
    messages = state.get("messages", [])
    kept = trim_history(messages, app_config.CHAT_HISTORY_MAX_TOKENS)

    trace = NodeTrace(
        node="history",
        status="ok",
        duration_ms=clock.ms(),
        details={"kept": _summary(kept), "dropped": len(messages) - len(kept)},
    )
    # `messages` uses the add_messages reducer: clear it, then write the trimmed list back.
    return {
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *kept],
        "node_traces": [trace],
    }
