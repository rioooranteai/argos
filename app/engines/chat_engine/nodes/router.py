from __future__ import annotations

import json
import logging
from pathlib import Path

from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.outcome import NodeTrace
from app.infrastructure.interface.llm import BaseLLM

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parents[4] / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file tidak ditemukan: {path}")


_ROUTER_SYSTEM = _load_prompt("router_agent.md")


async def router_node(state: dict, llm: BaseLLM) -> dict:
    user_input = state["user_input"]
    messages = state.get("messages", [])

    recent_history = messages[-6:] if len(messages) > 6 else messages
    history_text = "\n".join(
        f"{getattr(m, 'type', 'user').upper()}: {getattr(m, 'content', '')}"
        for m in recent_history
    )

    prompt = (
        f"Riwayat percakapan terakhir:\n{history_text}\n\n"
        f"Pertanyaan terbaru user: {user_input}"
    )

    clock = Stopwatch()
    try:
        raw = await llm.ainvoke(prompt=prompt, system=_ROUTER_SYSTEM)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)

        route = parsed.get("route", "none")
        reasoning = parsed.get("reasoning", "")

        if route not in ("sql", "vector", "both", "none"):
            route = "vector"

        trace = NodeTrace(node="router", status="ok", duration_ms=clock.ms())
        return {"route": route, "router_reasoning": reasoning, "node_traces": [trace]}

    except Exception:
        logger.exception("[router] Gagal menentukan rute; memakai rute cadangan.")
        trace = NodeTrace(node="router", status="error", duration_ms=clock.ms(), code="ROUTER_FAILED")
        return {
            "route": "vector",
            "router_reasoning": "Rute cadangan karena pemilihan sumber gagal.",
            "node_traces": [trace],
        }
