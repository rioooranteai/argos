from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.conversation.model import Conversation, Message


class BaseConversationRepository(ABC):
    """Persistence contract for conversations + messages.

    Every method that takes a `user_id` does the owner check in the adapter:
    it MUST return None / raise / no-op when that user does not own the
    conversation. No method bypasses the owner check.
    """

    @abstractmethod
    def create_conversation(
        self, user_id: str, title: str, notebook_id: str | None = None
    ) -> Conversation:
        """Create a new conversation. Returns the entity with its generated id (UUID)."""

    @abstractmethod
    def list_conversations(
        self, user_id: str, limit: int = 100, notebook_id: str | None = None
    ) -> list[Conversation]:
        """List every conversation of the user, newest first (by updated_at DESC)."""

    @abstractmethod
    def get_conversation(self, conversation_id: str, user_id: str) -> Conversation | None:
        """Get one conversation. Returns None when missing or not owned by the user."""

    @abstractmethod
    def update_title(self, conversation_id: str, user_id: str, title: str) -> bool:
        """Update the title. Returns True when a row was updated."""

    @abstractmethod
    def touch(self, conversation_id: str) -> None:
        """Set updated_at to CURRENT_TIMESTAMP. Called after a new message."""

    @abstractmethod
    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """Delete a conversation + all its messages (CASCADE). Returns True on success."""

    @abstractmethod
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        source_snapshot: list[str] | None = None,
        citations: list[dict] | None = None,
        trace: dict | None = None,
    ) -> Message:
        """Append one message to a conversation. No owner check here —
        the caller (ConversationService) must already have verified ownership."""

    @abstractmethod
    def get_message(self, message_id: str) -> Message | None:
        """One message by ID. Not owner-checked."""

    @abstractmethod
    def set_message_status(
        self,
        message_id: str,
        status: str,
        error_code: str | None = None,
        source_snapshot: list[str] | None = None,
    ) -> None:
        """Change a message's status (`ok` / `failed`). `source_snapshot` None = unchanged."""

    @abstractmethod
    def list_messages(
        self, conversation_id: str, limit: int | None = None, status: str | None = None
    ) -> list[Message]:
        """List the messages of one conversation in chronological order (created_at ASC).

        Not owner-checked at this level — the caller is responsible. Limit None = all.
        """
