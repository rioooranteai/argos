from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field


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


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationDetailOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, description="Optional initial title.")


class RenameConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User message.")
    conversation_id: str | None = Field(
        default=None,
        description="Existing thread ID. If null, a new thread is created and its ID returned.",
    )


class ChatResponse(BaseModel):
    conversation_id: str
    question: str
    answer: str
    metadata: dict
