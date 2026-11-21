from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    """A vector search result, independent of the provider's response format (Chroma, etc.)."""

    id: str
    text: str
    distance: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AddChunksResult:
    """Result of storing chunks: the stored IDs and how many reused their vectors."""

    ids: list[str]
    reused: int = 0
