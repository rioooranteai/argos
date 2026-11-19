from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    """Hasil pencarian vector, bebas dari format respons provider (Chroma, dll.)."""

    id: str
    text: str
    distance: float | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AddChunksResult:
    """Hasil penyimpanan chunk: ID yang tersimpan dan berapa yang vektornya dipakai ulang."""

    ids: list[str]
    reused: int = 0
