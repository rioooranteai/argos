from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.core.errors import ConflictError, NotFoundError
from app.services.conversation.ports import BaseConversationRepository
from app.tools.llm.base import BaseLLM
from app.services.conversation.model import Conversation, Message

logger = logging.getLogger(__name__)

_MAX_TITLE_CHARS = 60
_FALLBACK_TITLE = "New chat"

_TITLE_SYSTEM_PROMPT = (
    "You write short titles for chat threads. "
    "From the user's first message, write a title of at most 5 words, "
    "in the same language as that message, with no quotes, no trailing period "
    "and no emoji. The title is descriptive — not a greeting, not the question repeated."
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
            repository: BaseConversationRepository,
            title_llm: BaseLLM | None = None,
    ):
        self._repo = repository
        self._title_llm = title_llm

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

    def list_for_notebook(self, user_id: str, notebook_id: str, limit: int = 100) -> list[Conversation]:
        return self._repo.list_conversations(user_id, limit=limit, notebook_id=notebook_id)

    def create_for_user(
            self, user_id: str, first_message: str | None = None, notebook_id: str | None = None
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
        return self._repo.create_conversation(user_id=user_id, title=title, notebook_id=notebook_id)

    def rename(self, conversation_id: str, user_id: str, new_title: str) -> bool:
        cleaned = _normalize_title(new_title)
        return self._repo.update_title(conversation_id, user_id, cleaned)

    def delete(self, conversation_id: str, user_id: str) -> bool:
        return self._repo.delete_conversation(conversation_id, user_id)

    def append_user_message(
            self,
            conversation_id: str,
            user_id: str,
            content: str,
            source_snapshot: list[str] | None = None,
    ) -> Message | None:
        """Owner-checked append. Returns None if conversation isn't owned by user."""
        if self._repo.get_conversation(conversation_id, user_id) is None:
            return None
        msg = self._repo.add_message(
            conversation_id, role="user", content=content, source_snapshot=source_snapshot
        )
        self._repo.touch(conversation_id)
        return msg

    def append_assistant_message(
            self,
            conversation_id: str,
            content: str,
            citations: list[dict] | None = None,
            trace: dict | None = None,
    ) -> Message:
        """No owner check — caller is the chat router which already verified
        ownership when it accepted the user message."""
        msg = self._repo.add_message(
            conversation_id, role="assistant", content=content, citations=citations, trace=trace
        )
        self._repo.touch(conversation_id)
        return msg

    def mark_failed(self, message_id: str, error_code: str) -> None:
        """A user message got no answer (DESIGN_GROUP_C.md §4)."""
        self._repo.set_message_status(message_id, "failed", error_code)

    def prepare_retry(
            self,
            conversation_id: str,
            user_id: str,
            message_id: str,
            source_snapshot: list[str],
    ) -> Message:
        """Validate & reopen a `failed` user message so it can run again.

        Only the last message in the conversation may be resent, so its answer
        cannot appear after a newer question and answer.
        """
        if self._repo.get_conversation(conversation_id, user_id) is None:
            raise NotFoundError("Conversation not found.")
        msg = self._repo.get_message(message_id)
        if msg is None or msg.conversation_id != conversation_id or msg.role != "user":
            raise NotFoundError("Message not found.", code="MESSAGE_NOT_FOUND")
        if msg.status != "failed":
            raise ConflictError("This message did not fail, so there is nothing to resend.",
                                code="MESSAGE_NOT_FAILED")
        latest = self._repo.list_messages(conversation_id)[-1]
        if latest.id != msg.id:
            raise ConflictError("Only the last message can be resent.",
                                code="MESSAGE_NOT_LATEST")
        self._repo.set_message_status(message_id, "ok", None, source_snapshot=source_snapshot)
        self._repo.touch(conversation_id)
        return self._repo.get_message(message_id)  # type: ignore[return-value]

    def is_first_message(self, conversation_id: str, message_id: str) -> bool:
        first = self._repo.list_messages(conversation_id, limit=1)
        return bool(first) and first[0].id == message_id

    def get_messages_for_engine(
            self, conversation_id: str, user_id: str
    ) -> list[Message] | None:
        """History for the chat engine: `ok` messages only (failed ones never reach the LLM).

        Returns None if conversation is not owned by user.
        """
        if self._repo.get_conversation(conversation_id, user_id) is None:
            return None
        return self._repo.list_messages(conversation_id, status="ok")

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
            "The user's first message:\n"
            f"\"{first_user_message.strip()}\"\n\n"
            "Write the thread title (max 5 words, same language as the message, no quotes)."
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
