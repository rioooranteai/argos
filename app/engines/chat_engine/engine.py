from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.interface.llm import BaseLLM
from app.engines.chat_engine.graph import build_graph
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)

class ChatEngine:
    """
    Entry point untuk sistem chatbot competitive intelligence berbasis LangGraph.

    Engine ini mengorkestrasi:
    - Router (LLM memutuskan sumber data)
    - SQL node (query terstruktur via NL2SQLService)
    - Vector node (pencarian semantik via VectorStoreService)
    - Synthesizer (gabungkan hasil → jawaban natural language)

    Conversation history dikelola internal per sesi (in-memory).
    Untuk persistent history, ganti `self._history` dengan database/cache.
    """

    def __init__(
        self,
        llm: BaseLLM,
        nl2sql_svc: NL2SQLService,
        vector_svc: VectorStoreService,
    ):
        self._graph = build_graph(
            llm=llm,
            nl2sql_svc=nl2sql_svc,
            vector_svc=vector_svc,
        )
        # In-memory conversation history per session
        # Key: session_id, Value: list of message dicts
        self._history: dict[str, list[dict]] = {}
        logger.info("ChatEngine siap.")

    async def chat(self, user_input: str, session_id: str = "default") -> dict[str, Any]:
        """
        Proses satu giliran percakapan.

        Args:
            user_input: Pertanyaan dari user.
            session_id: ID sesi untuk isolasi conversation history antar user.

        Returns:
            dict berisi:
            - answer: str — jawaban final
            - route: str — keputusan router (sql/vector/both/none)
            - router_reasoning: str — alasan routing (untuk debugging)
            - sql_result: dict | None — raw result dari SQL node
            - vector_result: list | None — raw result dari vector node
        """
        logger.info(f"[ChatEngine] session={session_id} | input='{user_input}'")

        # Ambil history sesi ini (buat baru kalau belum ada)
        session_history = self._history.get(session_id, [])

        # Bangun initial state
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

        self._history[session_id] = final_state["messages"]

        return {
            "answer": final_state["final_answer"],
            "route": final_state["route"],
            "router_reasoning": final_state["router_reasoning"],
            "sql_result": final_state["sql_result"],
            "vector_result": final_state["vector_result"],
            "error": final_state.get("error"),
        }

    def clear_history(self, session_id: str = "default") -> None:
        """Reset conversation history untuk sesi tertentu."""
        self._history.pop(session_id, None)
        logger.info(f"[ChatEngine] History sesi '{session_id}' dihapus.")

    def get_history(self, session_id: str = "default") -> list[dict]:
        """Ambil conversation history untuk sesi tertentu."""
        return self._history.get(session_id, [])