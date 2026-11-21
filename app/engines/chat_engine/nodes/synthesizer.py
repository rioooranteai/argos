from __future__ import annotations

import logging

from app.core.errors import UpstreamError
from app.core.llm_errors import classify_llm_error
from app.core.observability.telemetry import spans
from app.engines.chat_engine.citations import CitationRegistry
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import COMPONENT_LABELS, RETRIEVAL_NODES, NodeTrace
from app.engines.chat_engine.prompt_blocks import build_prompt, load_prompt
from app.services.nl2sql.service import NL2SQLResult
from app.tools.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_SYNTHESIZER_INSTRUCTIONS = load_prompt("synthesizer_answer.md")

# Max SQL rows sent to the answering LLM (the rest are only counted)
MAX_SQL_ROWS_IN_PROMPT = 30
_CITATION_COLUMNS = ("version_id", "page_number")


def _format_sql_result(sql_result: NL2SQLResult | None, registry: CitationRegistry) -> str:
    if sql_result is None or sql_result.status != "ok" or not sql_result.raw_data:
        return ""

    rows = sql_result.raw_data
    shown = rows[:MAX_SQL_ROWS_IN_PROMPT]

    if sql_result.is_row_level:
        lines = ["[STRUCTURED DATA (SQL) — cite the label of every fact]"]
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
        # Aggregates: cannot be attributed per row → only a coverage summary.
        lines = [
            f"[AGGREGATED DATA (SQL) from {registry.coverage()} — "
            "mention this source coverage, do not add citation numbers]"
        ]
        for row in shown:
            lines.append(" | ".join(f"{k}={v}" for k, v in row.items() if v not in (None, "")))

    if sql_result.truncated or sql_result.row_count > len(shown):
        lines.append(f"... (showing the first {len(shown)} rows)")
    return "\n".join(lines)


def _format_vector_result(vector_result: list | None, registry: CitationRegistry) -> str:
    if not vector_result:
        return ""
    lines = ["[DOCUMENT CONTEXT (Vector Store) — cite the label of every fact]"]
    for i, chunk in enumerate(vector_result, 1):
        meta = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
        label = registry.label_for(
            meta.get("version_id"), meta.get("page_number"), meta.get("section_heading")
        )
        lines.append(f"{i}. {text} {label}".rstrip())
    return "\n".join(lines)


def _failure_note(failed: list[str]) -> str:
    """Block for the synthesizer when some sources failed to load (degraded answer)."""
    if not failed:
        return ""
    names = ", ".join(COMPONENT_LABELS.get(n, n) for n in failed)
    return (
        "[SYSTEM NOTE]\n"
        f"These sources FAILED to load because of a system problem: {names}. "
        "Their data is unavailable, not empty."
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
        sections.append("[SOURCE LIST]\n" + legend)
    note = _failure_note(failed or [])
    if note:
        sections.append(note)
    return "\n\n".join(sections)


def _retrieval_status(state: dict) -> tuple[list[str], list[str]]:
    """(retrieval nodes that ran, those that failed) from the trace so far."""
    ran = [t for t in state.get("node_traces", []) if t.node in RETRIEVAL_NODES]
    return [t.node for t in ran], [t.node for t in ran if t.status == "error"]


def _chunk_refs(vector_result: list | None, registry: CitationRegistry) -> list[dict]:
    """Chunk summary for the trace: label, page, distance. No document text."""
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


@traced_node(
    "synthesis", spans.CHAIN,
    inputs=lambda state: {"question": state["user_input"], "route": state.get("route")},
    outputs=lambda result: {"answer": result["final_answer"], "citations": result["citations"]},
)
async def synthesizer_node(state: dict, llm: BaseLLM) -> dict:
    clock = Stopwatch()
    user_input = state["user_input"]
    messages = state.get("messages", [])
    registry = CitationRegistry(state.get("sources") or [])

    ran, failed = _retrieval_status(state)
    if ran and len(failed) == len(ran):
        # Every source failed: do not let the LLM answer "no data" (C2).
        raise UpstreamError(
            "The data sources cannot be read right now. Try again shortly.",
            details={"issues": [
                {"component": t.node, "code": t.code}
                for t in state["node_traces"] if t.node in failed
            ]},
        )

    data_context = _build_data_context(
        state.get("sql_result"), state.get("vector_result"), registry, failed
    )

    # One message, fixed block order: HISTORY → DATA → INSTRUCTIONS → QUESTION → CURRENT_DATE.
    prompt = build_prompt(
        history=messages,
        data=data_context or "No data found.",
        instructions=_SYNTHESIZER_INSTRUCTIONS,
        question=user_input,
    )

    try:
        answer = await llm.ainvoke(prompt=prompt, system=None)
    except Exception as e:
        # No substitute answer is saved as the answer (C2).
        logger.exception("[synthesizer] Failed to produce an answer.")
        raise UpstreamError(
            "The AI service failed to produce an answer. Try again shortly.",
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
