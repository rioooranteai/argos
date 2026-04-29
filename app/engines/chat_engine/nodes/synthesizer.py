from __future__ import annotations

import logging

from app.infrastructure.interface.llm import BaseLLM

logger = logging.getLogger(__name__)

_SYNTHESIZER_SYSTEM = """
Kamu adalah asisten competitive intelligence yang cerdas dan ringkas.
Tugasmu: menjawab pertanyaan user berdasarkan data yang tersedia.

Aturan:
- Jawab dalam Bahasa Indonesia yang natural dan profesional.
- Jika ada data SQL (terstruktur), gunakan untuk fakta spesifik seperti harga dan fitur.
- Jika ada data dari dokumen (vector), gunakan untuk konteks dan penjelasan mendalam.
- Jika kedua data ada, gabungkan secara kohesif — jangan tampilkan dua blok terpisah.
- Jika data tidak tersedia atau kosong, katakan dengan jujur bahwa informasi tidak ditemukan.
- Jangan mengarang data yang tidak ada dalam input.
- Jawaban maksimal 400 kata kecuali diminta lebih panjang.
""".strip()


def _format_sql_result(sql_result: dict | None) -> str:
    if not sql_result or sql_result.get("status") == "error":
        return ""
    rows = sql_result.get("raw_data", [])
    if not rows:
        return ""
    lines = ["[DATA TERSTRUKTUR (SQL)]"]
    for row in rows[:20]:
        lines.append(str(row))
    if sql_result.get("truncated"):
        lines.append(f"... (total {sql_result.get('row_count')} baris)")
    return "\n".join(lines)


def _format_vector_result(vector_result: list | None) -> str:
    if not vector_result:
        return ""
    lines = ["[KONTEKS DOKUMEN (Vector Store)]"]
    for i, chunk in enumerate(vector_result, 1):
        if isinstance(chunk, dict):
            text = chunk.get("text") or chunk.get("content") or chunk.get("page_content", "")
            source = chunk.get("metadata", {}).get("source", "")
            entry = f"{i}. {text}"
            if source:
                entry += f" (sumber: {source})"
        else:
            entry = f"{i}. {str(chunk)}"
        lines.append(entry)
    return "\n".join(lines)


def _message_to_text(m) -> str:
    role = getattr(m, "type", "user")
    content = getattr(m, "content", "")

    if isinstance(content, list):
        content = " ".join(
            part.get("text", str(part)) if isinstance(part, dict) else str(part)
            for part in content
        )

    return f"{str(role).upper()}: {content}"


async def synthesizer_node(state: dict, llm: BaseLLM) -> dict:
    user_input = state["user_input"]
    messages = state.get("messages", [])
    sql_result = state.get("sql_result")
    vector_result = state.get("vector_result")

    logger.debug("[synthesizer] Menyintesis jawaban...")

    sql_section = _format_sql_result(sql_result)
    vector_section = _format_vector_result(vector_result)

    data_parts = [s for s in [sql_section, vector_section] if s]
    data_context = "\n\n".join(data_parts) if data_parts else "Tidak ada data yang ditemukan."

    recent_history = messages[-6:] if len(messages) > 6 else messages
    history_text = "\n".join(_message_to_text(m) for m in recent_history)

    prompt = (
        f"Riwayat percakapan:\n{history_text}\n\n"
        f"Pertanyaan user: {user_input}\n\n"
        f"Data yang tersedia:\n{data_context}"
    )

    try:
        answer = await llm.ainvoke(prompt=prompt, system=_SYNTHESIZER_SYSTEM)
        logger.info("[synthesizer] Jawaban berhasil di-generate.")
    except Exception as e:
        logger.error(f"[synthesizer] Error: {e}")
        answer = "Maaf, terjadi kesalahan saat membuat jawaban."

    return {
        "final_answer": answer
    }
