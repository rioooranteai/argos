from __future__ import annotations

import logging
from pathlib import Path

from app.core.errors import UpstreamError
from app.core.llm_errors import classify_llm_error
from app.engines.chat_engine.citations import CitationRegistry
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.outcome import COMPONENT_LABELS, RETRIEVAL_NODES, NodeTrace
from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.service import NL2SQLResult

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parents[4] / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file tidak ditemukan: {path}") from None


_SYNTHESIZER_PROMPT_TEXT = _load_prompt("synthesizer_answer.md")

# Baris SQL maksimum yang dikirim ke LLM penjawab (sisanya hanya diringkas jumlahnya)
MAX_SQL_ROWS_IN_PROMPT = 30
_CITATION_COLUMNS = ("version_id", "page_number")


def _format_sql_result(sql_result: NL2SQLResult | None, registry: CitationRegistry) -> str:
    if sql_result is None or sql_result.status != "ok" or not sql_result.raw_data:
        return ""

    rows = sql_result.raw_data
    shown = rows[:MAX_SQL_ROWS_IN_PROMPT]

    if sql_result.is_row_level:
        lines = ["[DATA TERSTRUKTUR (SQL) — sebutkan label sitasi setiap fakta]"]
        for row in shown:
            label = registry.label_for(
                row.get("version_id"), row.get("page_number"), row.get("section_heading")
            )
            body = " | ".join(
                f"{k}={v}"
                for k, v in row.items()
                if k not in _CITATION_COLUMNS and k != "section_heading" and v not in (None, "")
            )
            lines.append(f"{body} {label}".rstrip())
    else:
        # Agregat: tidak bisa diatribusikan per baris → ringkasan cakupan saja.
        lines = [
            f"[DATA AGREGAT (SQL) dari {registry.coverage()} — "
            "sebutkan cakupan sumber ini, jangan beri nomor sitasi]"
        ]
        for row in shown:
            lines.append(" | ".join(f"{k}={v}" for k, v in row.items() if v not in (None, "")))

    if sql_result.truncated or sql_result.row_count > len(shown):
        lines.append(f"... (ditampilkan {len(shown)} baris pertama)")
    return "\n".join(lines)


def _format_vector_result(vector_result: list | None, registry: CitationRegistry) -> str:
    if not vector_result:
        return ""
    lines = ["[KONTEKS DOKUMEN (Vector Store) — sebutkan label sitasi setiap fakta]"]
    for i, chunk in enumerate(vector_result, 1):
        meta = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
        label = registry.label_for(
            meta.get("version_id"), meta.get("page_number"), meta.get("section_heading")
        )
        lines.append(f"{i}. {text} {label}".rstrip())
    return "\n".join(lines)


def _failure_note(failed: list[str]) -> str:
    """Blok untuk synthesizer saat sebagian sumber gagal dibaca (jawaban degraded)."""
    if not failed:
        return ""
    names = ", ".join(COMPONENT_LABELS.get(n, n) for n in failed)
    return (
        "[CATATAN SISTEM]\n"
        f"Sumber berikut GAGAL dibaca karena gangguan sistem: {names}. "
        "Data dari sumber itu tidak tersedia, bukan kosong."
    )


def _build_data_context(
    sql_result, vector_result, registry: CitationRegistry, failed: list[str] | None = None
) -> str:
    sections = [
        s for s in (
            _format_sql_result(sql_result, registry),
            _format_vector_result(vector_result, registry),
        ) if s
    ]
    legend = registry.legend()
    if sections and legend:
        sections.append("[DAFTAR SUMBER]\n" + legend)
    note = _failure_note(failed or [])
    if note:
        sections.append(note)
    return "\n\n".join(sections)


def _retrieval_status(state: dict) -> tuple[list[str], list[str]]:
    """(node pengambil data yang berjalan, yang gagal) dari trace sejauh ini."""
    ran = [t for t in state.get("node_traces", []) if t.node in RETRIEVAL_NODES]
    return [t.node for t in ran], [t.node for t in ran if t.status == "error"]


def _message_to_text(m) -> str:
    role = getattr(m, "type", "user")
    content = getattr(m, "content", "")
    if isinstance(content, list):
        content = " ".join(
            part.get("text", str(part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    return f"{str(role).upper()}: {content}"


def _chunk_refs(vector_result: list | None, registry: CitationRegistry) -> list[dict]:
    """Ringkasan chunk untuk trace: label, halaman, jarak. Tanpa teks dokumen."""
    refs = []
    for chunk in vector_result or []:
        meta = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        refs.append({
            "label": registry.label_for(
                meta.get("version_id"), meta.get("page_number"), meta.get("section_heading")
            ),
            "page": meta.get("page_number"),
            "distance": round(chunk["distance"], 4) if chunk.get("distance") is not None else None,
        })
    return refs


async def synthesizer_node(state: dict, llm: BaseLLM) -> dict:
    clock = Stopwatch()
    user_input = state["user_input"]
    messages = state.get("messages", [])
    registry = CitationRegistry(state.get("sources") or [])

    ran, failed = _retrieval_status(state)
    if ran and len(failed) == len(ran):
        # Semua sumber gagal: jangan biarkan LLM menjawab "tidak ada data" (C2).
        raise UpstreamError(
            "Sumber data sedang tidak bisa dibaca. Coba lagi sebentar.",
            details={"issues": [
                {"component": t.node, "code": t.code}
                for t in state["node_traces"] if t.node in failed
            ]},
        )

    data_context = _build_data_context(
        state.get("sql_result"), state.get("vector_result"), registry, failed
    )

    recent_history = messages[-6:] if len(messages) > 6 else messages
    history_text = "\n".join(_message_to_text(m) for m in recent_history)

    prompt_body = _SYNTHESIZER_PROMPT_TEXT.format(
        question=user_input,
        data=data_context if data_context else "Tidak ada data yang ditemukan.",
    )
    prompt = f"Riwayat percakapan:\n{history_text}\n\n{prompt_body}"

    try:
        answer = await llm.ainvoke(prompt=prompt, system=None)
    except Exception as e:
        # Tidak ada jawaban pengganti yang disimpan sebagai jawaban (C2).
        logger.exception("[synthesizer] Gagal membuat jawaban.")
        raise UpstreamError(
            "Layanan AI gagal membuat jawaban. Coba lagi sebentar.",
            details={"issues": [{"component": "synthesizer", "code": classify_llm_error(e)}]},
        ) from e

    trace = NodeTrace(
        node="synthesizer",
        status="ok",
        duration_ms=clock.ms(),
        details={"chunks": _chunk_refs(state.get("vector_result"), registry)},
    )
    return {
        "final_answer": answer,
        "citations": [c.to_dict() for c in registry.used_in(answer)],
        "node_traces": [trace],
    }
