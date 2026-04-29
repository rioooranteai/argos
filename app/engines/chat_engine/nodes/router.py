from __future__ import annotations

import json
import logging

from app.infrastructure.interface.llm import BaseLLM

logger = logging.getLogger(__name__)

_ROUTER_SYSTEM = """
Kamu adalah router untuk sistem competitive intelligence chatbot.
Tugasmu adalah memutuskan sumber data mana yang paling tepat untuk menjawab pertanyaan user.

Kamu memiliki dua sumber data:
1. **SQL (SQLite)** — berisi data TERSTRUKTUR kompetitor:
   - Harga produk (price)
   - Nama fitur (feature_name)
   - Kelebihan / keunggulan (advantages)
   - Kelemahan / kekurangan (disadvantages)
   - Nama kompetitor (competitor_name)
   Gunakan SQL untuk pertanyaan: perbandingan harga, daftar fitur, ranking, filter spesifik.

2. **Vector Store (ChromaDB)** — berisi data SEMANTIK / KONTEKSTUAL:
   - Isi dokumen lengkap (artikel, laporan, deskripsi produk)
   - Analisis naratif kompetitor
   Gunakan Vector Store untuk pertanyaan: penjelasan mendalam, konteks, ringkasan dokumen.

3. **Both** — gunakan keduanya jika pertanyaan membutuhkan data terstruktur DAN konteks naratif.

4. **None** — jika pertanyaan sama sekali tidak relevan dengan competitive intelligence.

Balas HANYA dalam format JSON berikut, tanpa preamble atau markdown:
{
  "route": "sql" | "vector" | "both" | "none",
  "reasoning": "alasan singkat dalam satu kalimat"
}
""".strip()


async def router_node(state: dict, llm: BaseLLM) -> dict:
    user_input = state["user_input"]
    messages = state.get("messages", [])

    logger.debug(f"[router] Memproses: '{user_input}'")

    recent_history = messages[-6:] if len(messages) > 6 else messages
    history_text = "\n".join(
        f"{getattr(m, 'type', 'user').upper()}: {getattr(m, 'content', '')}"
        for m in recent_history
    )

    prompt = (
        f"Riwayat percakapan terakhir:\n{history_text}\n\n"
        f"Pertanyaan terbaru user: {user_input}"
    )

    try:
        raw = await llm.ainvoke(prompt=prompt, system=_ROUTER_SYSTEM)
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)

        route = parsed.get("route", "none")
        reasoning = parsed.get("reasoning", "")

        if route not in ("sql", "vector", "both", "none"):
            logger.warning(f"[router] Route tidak valid '{route}', fallback ke 'vector'")
            route = "vector"

        logger.info(f"[router] Route: {route} | Alasan: {reasoning}")
        return {"route": route, "router_reasoning": reasoning}

    except Exception as e:
        logger.error(f"[router] Gagal parse response LLM: {e}")
        return {"route": "vector", "router_reasoning": "Fallback karena error parsing router"}