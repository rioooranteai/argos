from dataclasses import dataclass
from datetime import datetime


@dataclass
class Conversation:
    """Satu thread percakapan (entry di sidebar UI)."""

    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass
class Message:
    """Satu pesan (user atau assistant) dalam sebuah thread."""

    id: int
    conversation_id: str
    role: str  # 'user' | 'assistant'
    content: str
    created_at: datetime
