from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.conversation.model import Conversation, Message


class ConversationRepository(ABC):
    """Kontrak persistence untuk conversations + messages.

    Semua method yang menerima `user_id` melakukan owner check di adapter:
    method WAJIB return None / raise / no-op bila conversation tidak dimiliki
    user tersebut. Tidak ada method yang membypass owner check.
    """

    @abstractmethod
    def create_conversation(self, user_id: str, title: str) -> Conversation:
        """Buat conversation baru. Return entity dengan id (UUID) yang sudah generated."""

    @abstractmethod
    def list_conversations(self, user_id: str, limit: int = 100) -> list[Conversation]:
        """List semua conversation milik user, terbaru di atas (by updated_at DESC)."""

    @abstractmethod
    def get_conversation(self, conversation_id: str, user_id: str) -> Conversation | None:
        """Ambil 1 conversation. Return None bila tidak ada atau bukan milik user."""

    @abstractmethod
    def update_title(self, conversation_id: str, user_id: str, title: str) -> bool:
        """Update title. Return True bila ada row yang ter-update."""

    @abstractmethod
    def touch(self, conversation_id: str) -> None:
        """Update updated_at ke CURRENT_TIMESTAMP. Dipanggil setelah ada message baru."""

    @abstractmethod
    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """Hapus conversation + semua messages-nya (CASCADE). Return True bila berhasil."""

    @abstractmethod
    def add_message(self, conversation_id: str, role: str, content: str) -> Message:
        """Append 1 message ke conversation. Tidak melakukan owner check di sini —
        caller (ConversationService) wajib sudah memverifikasi ownership."""

    @abstractmethod
    def list_messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        """List messages dalam 1 conversation, urut kronologis (created_at ASC).

        Tidak owner-checked di level ini — caller bertanggung jawab. Limit None = semua.
        """
