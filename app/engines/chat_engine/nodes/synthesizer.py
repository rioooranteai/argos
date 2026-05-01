from __future__ import annotations

import logging
from pathlib import Path

from app.infrastructure.interface.llm import BaseLLM

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parents[4] / "prompts"

def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file tidak ditemukan: {path}")


_SYNTHESIZER_PROMPT_TEXT = _load_prompt("synthesizer_answer.md")


def _format_sql_result(sql_result: dict | None) -> str:
    if not sql_result or sql_result.get("status") == "error":
        return ""

    rows = sql_result.get("raw_data", [])
    if not rows:
        return ""

    lines = ["[DATA TERSTRUKTUR (SQL)]"]
    for row in rows:
        lines.append(str(row))

    if sql_result.get("truncated"):
        lines.append(
            f"... (total {sql_result.get('row_count')} baris, ditampilkan {len(rows)})"
        )

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


def _build_data_context(sql_result: dict | None, vector_result: list | None) -> str:
    sql_section = _format_sql_result(sql_result)
    vector_section = _format_vector_result(vector_result)

    has_sql = bool(sql_section)
    has_vector = bool(vector_section)

    parts: list[str] = []

    if has_sql and has_vector:
        parts.append(
            "Sumber data yang tersedia: SQL terstruktur dan dokumen hasil retrieval vector store.\n"
            "Gunakan SQL untuk fakta spesifik seperti angka, harga, fitur, dan metrik.\n"
            "Gunakan dokumen untuk konteks, penjelasan, dan detail tambahan."
        )
    elif has_sql:
        parts.append(
            "Sumber data yang tersedia: SQL terstruktur.\n"
            "Gunakan data ini untuk menjawab secara faktual dan spesifik."
        )
    elif has_vector:
        parts.append(
            "Sumber data yang tersedia: dokumen hasil retrieval vector store.\n"
            "Gunakan data ini untuk menjawab berdasarkan konteks dokumen yang ditemukan."
        )
    else:
        return ""

    if has_sql:
        parts.append(sql_section)

    if has_vector:
        parts.append(vector_section)

    return "\n\n".join(parts)


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

    data_context = _build_data_context(sql_result, vector_result)

    recent_history = messages[-6:] if len(messages) > 6 else messages
    history_text = "\n".join(_message_to_text(m) for m in recent_history)

    prompt_body = _SYNTHESIZER_PROMPT_TEXT.format(
        question=user_input,
        data=data_context if data_context else "Tidak ada data yang ditemukan."
    )

    prompt = (
        f"Riwayat percakapan:\n{history_text}\n\n"
        f"{prompt_body}"
    )

    try:
        answer = await llm.ainvoke(prompt=prompt, system=None)
        logger.info("[synthesizer] Jawaban berhasil di-generate.")
    except Exception as e:
        logger.error(f"[synthesizer] Error: {e}")
        answer = "Maaf, terjadi kesalahan saat membuat jawaban."

    return {
        "final_answer": answer
    }