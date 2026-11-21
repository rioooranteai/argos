"""HTTP request/response schemas for conversation (DESIGN_GROUP_E.md §3.7)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.conversation.model import Message


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    citations: list[dict] = Field(default_factory=list)
    status: str = "ok"
    error_code: str | None = None
    degraded: bool = False
    issues: list[dict] = Field(default_factory=list)
    trace: dict | None = None

    @classmethod
    def from_message(cls, m: "Message") -> "MessageOut":
        issues = (m.trace or {}).get("issues") or []
        return cls(
            id=m.id, role=m.role, content=m.content, created_at=m.created_at,
            citations=m.citations, status=m.status, error_code=m.error_code,
            degraded=bool(issues), issues=issues, trace=m.trace,
        )


class ConversationDetailOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


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
    citations: list[dict] = Field(default_factory=list)
    metadata: dict
