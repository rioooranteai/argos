"""ConversationService — orchestrates conversation lifecycle on top of the
ConversationRepository port.

Responsibilities (NOT in repository):
    - Auto-titling new threads via LLM (best-effort, errors swallowed).
    - Owner-checked rename / delete / fetch convenience.
    - Single source of truth for "list messages of a conversation that user X owns".

The service is deliberately thin. The repository handles SQL, the chat engine
handles the LangGraph flow, and the API router glues everything together.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.infrastructure.interface.llm import BaseLLM
from app.services.conversation.repository import (
    Conversation,
    ConversationRepository,
    Message,
)

logger = logging.getLogger(__name__)

# Title length budget — short enough for sidebar, long enough to be informative.
_MAX_TITLE_CHARS = 60
_FALLBACK_TITLE = "New chat"


_TITLE_SYSTEM_PROMPT = (
    "Anda generator judul ringkas untuk thread chat. "
    "Berdasarkan pesan pertama user, hasilkan judul maksimal 5 kata, "
    "dalam Bahasa Indonesia, tanpa tanda kutip, tanpa titik di akhir, "
    "tanpa emoji. Judul deskriptif — bukan greeting, bukan pertanyaan ulang."
)


def _placeholder_title_from_message(content: str) -> str:
    """Truncated first message — used until the LLM-generated title arrives."""
    cleaned = " ".join(content.strip().split())
    if not cleaned:
        return _FALLBACK_TITLE
    if len(cleaned) <= _MAX_TITLE_CHARS:
        return cleaned
    return cleaned[: _MAX_TITLE_CHARS - 1].rstrip() + "…"


def _normalize_title(raw: str) -> str:
    """Defensive cleanup on LLM output."""
    cleaned = " ".join(raw.strip().split())
    # Strip surrounding quotes that some LLMs add despite instructions.
    for q in ('"', "'", "“", "”", "‘", "’"):
        if cleaned.startswith(q) and cleaned.endswith(q):
            cleaned = cleaned[1:-1].strip()
    cleaned = cleaned.rstrip(".!?")
    if len(cleaned) > _MAX_TITLE_CHARS:
        cleaned = cleaned[: _MAX_TITLE_CHARS - 1].rstrip() + "…"
    return cleaned or _FALLBACK_TITLE


@dataclass
class ConversationWithMessages:
    """Convenience response container for `get_with_messages`."""

    conversation: Conversation
    messages: list[Message]


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        title_llm: BaseLLM | None = None,
    ):
        self._repo = repository
        self._title_llm = title_llm

    # ── Conversation lifecycle ─────────────────────────────────────────────

    def list_for_user(self, user_id: str, limit: int = 100) -> list[Conversation]:
        return self._repo.list_conversations(user_id, limit=limit)

    def get_with_messages(
        self, conversation_id: str, user_id: str
    ) -> ConversationWithMessages | None:
        conv = self._repo.get_conversation(conversation_id, user_id)
        if conv is None:
            return None
        msgs = self._repo.list_messages(conversation_id)
        return ConversationWithMessages(conversation=conv, messages=msgs)

    def create_for_user(
        self, user_id: str, first_message: str | None = None
    ) -> Conversation:
        """Create a new thread.

        If `first_message` is provided, it's used as a placeholder title
        (truncated). Caller may invoke `generate_title_async` later when the
        bot has responded so that the title becomes more meaningful.
        """
        title = (
            _placeholder_title_from_message(first_message)
            if first_message
            else _FALLBACK_TITLE
        )
        return self._repo.create_conversation(user_id=user_id, title=title)

    def rename(self, conversation_id: str, user_id: str, new_title: str) -> bool:
        cleaned = _normalize_title(new_title)
        return self._repo.update_title(conversation_id, user_id, cleaned)

    def delete(self, conversation_id: str, user_id: str) -> bool:
        return self._repo.delete_conversation(conversation_id, user_id)

    # ── Message persistence ────────────────────────────────────────────────

    def append_user_message(
        self, conversation_id: str, user_id: str, content: str
    ) -> Message | None:
        """Owner-checked append. Returns None if conversation isn't owned by user."""
        if self._repo.get_conversation(conversation_id, user_id) is None:
            return None
        msg = self._repo.add_message(conversation_id, role="user", content=content)
        self._repo.touch(conversation_id)
        return msg

    def append_assistant_message(
        self, conversation_id: str, content: str
    ) -> Message:
        """No owner check — caller is the chat router which already verified
        ownership when it accepted the user message."""
        msg = self._repo.add_message(conversation_id, role="assistant", content=content)
        self._repo.touch(conversation_id)
        return msg

    def get_messages_for_engine(
        self, conversation_id: str, user_id: str
    ) -> list[Message] | None:
        """Load full message history for feeding the chat engine.

        Returns None if conversation is not owned by user.
        """
        if self._repo.get_conversation(conversation_id, user_id) is None:
            return None
        return self._repo.list_messages(conversation_id)

    # ── Auto-title via LLM ─────────────────────────────────────────────────

    async def generate_title_async(
        self,
        conversation_id: str,
        user_id: str,
        first_user_message: str,
    ) -> None:
        """Generate a conversational title in the background. Best-effort —
        errors are logged but never propagated. Caller should fire-and-forget
        with `asyncio.create_task` so the chat response isn't blocked.
        """
        if self._title_llm is None:
            logger.debug("No title LLM configured — skipping auto-title generation.")
            return

        prompt = (
            "Pesan pertama user:\n"
            f"\"{first_user_message.strip()}\"\n\n"
            "Buat judul thread (maks 5 kata, Bahasa Indonesia, tanpa tanda kutip)."
        )

        try:
            raw = await self._title_llm.ainvoke(
                prompt=prompt, system=_TITLE_SYSTEM_PROMPT
            )
        except Exception:
            logger.exception("Auto-title LLM call failed (conversation=%s).", conversation_id)
            return

        title = _normalize_title(raw)
        if not title or title == _FALLBACK_TITLE:
            return

        try:
            updated = self._repo.update_title(conversation_id, user_id, title)
            if updated:
                logger.info(
                    "Auto-titled conversation=%s → %r", conversation_id, title
                )
        except Exception:
            logger.exception(
                "Failed to persist auto-generated title (conversation=%s).",
                conversation_id,
            )

    def schedule_auto_title(
        self,
        conversation_id: str,
        user_id: str,
        first_user_message: str,
    ) -> None:
        """Fire-and-forget wrapper. Safe to call from sync or async contexts —
        if no event loop is running, falls back to a no-op (cron / test paths).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running event loop — auto-title skipped.")
            return
        loop.create_task(
            self.generate_title_async(conversation_id, user_id, first_user_message)
        )
