"""Typed chat results and per-node status (DESIGN_GROUP_C.md §3).

Node status:
- ``ok``    — succeeded, with data
- ``empty`` — succeeded, there really is no data
- ``error`` — system failure (the code is in ``code``)

Every node adds one ``NodeTrace`` to the state (reducer ``operator.add``,
because ``sql_node`` and ``vector_node`` can run in parallel). The engine builds
the trace and the issue list from it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

NodeStatus = Literal["ok", "empty", "error"]

# Nodes that fetch data from the notebook sources (the others: router, synthesizer).
RETRIEVAL_NODES = ("sql", "vector")

# Source names for messages to the user / synthesizer.
COMPONENT_LABELS = {
    "sql": "Structured data (SQL)",
    "vector": "Document search",
    "router": "Source selection",
}


@dataclass(frozen=True)
class NodeIssue:
    component: str
    code: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class NodeTrace:
    """Summary of one node for the message trace. No document text / prompts."""

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
        """An answer was produced even though some component failed."""
        return bool(self.issues)


def issues_from(traces: list[NodeTrace]) -> list[NodeIssue]:
    return [NodeIssue(t.node, t.code or "ERROR") for t in traces if t.status == "error"]
