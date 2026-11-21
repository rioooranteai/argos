from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

Purpose = Literal[
    "router", "nl2sql", "synthesizer", "title", "vision", "extraction", "embedding", "stt", "tts"
]


@dataclass
class LLMCall:
    """One call to an AI service. Never contains prompts or document content."""

    purpose: str
    model: str
    latency_ms: int
    status: Literal["ok", "error"]
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None
    version_id: str | None = None
    message_id: str | None = None  # UUID of the triggering user message
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
