"""Hasil chat bertipe dan status per node (DESIGN_GROUP_C.md §3).

Status node:
- ``ok``    — berhasil, ada data
- ``empty`` — berhasil, memang tidak ada data
- ``error`` — sistem gagal (kode di ``code``)

Setiap node menambahkan satu ``NodeTrace`` ke state (reducer ``operator.add``,
karena ``sql_node`` dan ``vector_node`` bisa berjalan paralel). Engine menyusun
trace dan daftar issue dari situ.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

NodeStatus = Literal["ok", "empty", "error"]

# Node yang mengambil data dari sumber notebook (yang lain: router, synthesizer).
RETRIEVAL_NODES = ("sql", "vector")

# Nama sumber untuk pesan ke user / synthesizer.
COMPONENT_LABELS = {
    "sql": "Data terstruktur (SQL)",
    "vector": "Pencarian dokumen",
    "router": "Pemilihan sumber",
}


@dataclass(frozen=True)
class NodeIssue:
    component: str
    code: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class NodeTrace:
    """Ringkasan satu node untuk trace pesan. Tanpa teks dokumen / prompt."""

    node: str
    status: NodeStatus
    duration_ms: int
    code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "duration_ms": self.duration_ms}
        if self.code:
            out["code"] = self.code
        out.update(self.details)
        return out


@dataclass
class ChatResult:
    answer: str
    route: str
    router_reasoning: str
    citations: list[dict[str, Any]]
    issues: list[NodeIssue] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        """Jawaban dibuat walau ada komponen yang gagal."""
        return bool(self.issues)


def issues_from(traces: list[NodeTrace]) -> list[NodeIssue]:
    return [NodeIssue(t.node, t.code or "ERROR") for t in traces if t.status == "error"]
