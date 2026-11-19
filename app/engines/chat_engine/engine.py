from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from app.core.errors import UpstreamTimeout
from app.engines.chat_engine.graph import build_graph
from app.infrastructure.interface.llm import BaseLLM
from app.services.conversation.model import Message
from app.services.notebook.model import ActiveSource
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

logger = logging.getLogger(__name__)


def _to_lc_messages(messages: Iterable[Message] | Iterable[dict] | None) -> list[AnyMessage]:
    """Convert repository Messages (or plain dicts) into LangChain message objects.

    Tolerant of both shapes so that callers can pass either:
        - list[app.services.conversation.repository.Message]
        - list[{"role": str, "content": str}]
    """
    if not messages:
        return []

    out: list[AnyMessage] = []
    for m in messages:
        if isinstance(m, Message):
            role, content = m.role, m.content
        elif isinstance(m, dict):
            role, content = m.get("role"), m.get("content", "")
        else:  # pragma: no cover — defensive
            continue

        if not content:
            continue
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        # Silently ignore unknown roles (e.g. "system") — chat history shouldn't carry them.
    return out


class ChatEngine:
    """Stateless LangGraph orchestrator.

    History is now fully owned by ConversationService (persisted via the
    ConversationRepository). The engine receives the prior messages on every
    call and returns the assistant answer — it no longer mutates any store.

    The router/sql/vector/synthesizer nodes still see the user's *current*
    input both as `state["user_input"]` (legacy) and as the last HumanMessage
    inside `state["messages"]` (the bug-fix from the audit).
    """

    def __init__(
            self,
            llm: BaseLLM,
            nl2sql_svc: NL2SQLService,
            vector_svc: VectorStoreService,
            router_llm: BaseLLM | None = None,
            total_timeout: float = 90,
    ):
        self._total_timeout = total_timeout
        self._graph = build_graph(
            llm=llm,
            router_llm=router_llm,
            nl2sql_svc=nl2sql_svc,
            vector_svc=vector_svc,
        )

    async def chat(
            self,
            user_input: str,
            history: list[Message] | list[dict] | None = None,
            sources: list[ActiveSource] | None = None,
    ) -> dict[str, Any]:
        """Run the LangGraph pipeline with the given prior history.

        Args:
            user_input: The current user message (already saved to DB by caller).
            history: Prior messages in chronological order. The CURRENT user
                input should already be the last item — but we accept either
                shape and add it ourselves if missing, to keep callers simple.
            sources: Sumber aktif notebook (dicentang & ready). SQL dan vector
                search HANYA membaca data milik versi-versi ini.

        Raises:
            UpstreamTimeout: seluruh proses melewati CHAT_TOTAL_TIMEOUT.
        """
        sources = sources or []

        prior = _to_lc_messages(history)

        # Ensure the current user input is in `messages` so downstream nodes
        # that read `state["messages"]` see it. We check the last message to
        # avoid duplicating when the caller already appended it.
        if not prior or not (
                isinstance(prior[-1], HumanMessage) and prior[-1].content == user_input
        ):
            prior.append(HumanMessage(content=user_input))

        initial_state = {
            "user_input": user_input,
            "messages": prior,
            "route": "none",
            "router_reasoning": "",
            "sql_result": None,
            "vector_result": None,
            "final_answer": "",
            "error": None,
            "active_versions": [src.version_id for src in sources],
            "sources": sources,
            "citations": [],
        }

        try:
            final_state = await asyncio.wait_for(
                self._graph.ainvoke(initial_state), timeout=self._total_timeout
            )
        except TimeoutError:
            logger.warning("Chat melewati batas %s detik.", self._total_timeout)
            raise UpstreamTimeout("Jawaban terlalu lama dibuat. Coba lagi.", code="CHAT_TIMEOUT") from None

        return {
            "answer": final_state["final_answer"],
            "route": final_state["route"],
            "router_reasoning": final_state["router_reasoning"],
            "sql_result": final_state["sql_result"],
            "vector_result": final_state["vector_result"],
            "error": final_state.get("error"),
            "citations": final_state.get("citations", []),
        }
