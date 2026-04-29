from __future__ import annotations

import logging
from typing import Any

from app.engines.chat_engine.conversation_store import (
    ConversationStore,
    InMemoryConversationStore,
)
from app.engines.chat_engine.graph import build_graph
from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)


class ChatEngine:
    """Entry point for the LangGraph-based competitive intelligence chatbot.

    The engine orchestrates:
        - Router (LLM decides data source)
        - SQL node (NL2SQLService for structured queries)
        - Vector node (VectorStoreService for semantic search)
        - Synthesizer (combines results into a natural-language answer)

    Conversation history is delegated to a ConversationStore port. The default
    InMemoryConversationStore preserves legacy behavior; production deployments
    should inject SQLiteConversationStore (or a Redis-backed store) to survive
    container restarts.
    """

    def __init__(
        self,
        llm: BaseLLM,
        nl2sql_svc: NL2SQLService,
        vector_svc: VectorStoreService,
        conversation_store: ConversationStore | None = None,
    ):
        self._graph = build_graph(
            llm=llm,
            nl2sql_svc=nl2sql_svc,
            vector_svc=vector_svc,
        )
        self._history: ConversationStore = conversation_store or InMemoryConversationStore()
        logger.info("ChatEngine ready (history store: %s).", type(self._history).__name__)

    async def chat(self, user_input: str, session_id: str = "default") -> dict[str, Any]:
        logger.info(f"[ChatEngine] session={session_id} | input='{user_input}'")

        session_history = self._history.get(session_id)

        initial_state = {
            "user_input": user_input,
            "messages": session_history,
            "route": "none",
            "router_reasoning": "",
            "sql_result": None,
            "vector_result": None,
            "final_answer": "",
            "error": None,
        }

        final_state = await self._graph.ainvoke(initial_state)

        self._history.append(session_id, final_state["messages"])

        return {
            "answer": final_state["final_answer"],
            "route": final_state["route"],
            "router_reasoning": final_state["router_reasoning"],
            "sql_result": final_state["sql_result"],
            "vector_result": final_state["vector_result"],
            "error": final_state.get("error"),
        }

    def clear_history(self, session_id: str = "default") -> None:
        """Reset conversation history for a given session."""
        self._history.clear(session_id)
        logger.info(f"[ChatEngine] History for session '{session_id}' cleared.")

    def get_history(self, session_id: str = "default") -> list[dict]:
        """Return conversation history for a given session."""
        return self._history.get(session_id)
