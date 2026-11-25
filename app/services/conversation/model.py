from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Conversation:
    """One conversation thread (an entry in the UI sidebar)."""

    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    notebook_id: str | None = None


@dataclass
class Message:
    """One message (user or assistant) in a thread."""

    id: str  # UUID
    conversation_id: str
    role: str  # 'user' | 'assistant'
    content: str
    created_at: datetime
    source_snapshot: list[str] | None = None  # active version_ids when the message was sent
    citations: list[dict] = field(default_factory=list)
    # A user message with no answer → `failed` + error code.
    status: str = "ok"  # 'ok' | 'failed'
    error_code: str | None = None
    trace: dict | None = None  # assistant messages only
