"""Chat use cases: send a message and resend a failed one (DESIGN_GROUP_E.md §3.5).

Orchestrates three collaborators, all injected at startup:
- ``NotebookService``     — which sources are checked and ready;
- ``ConversationService`` — conversations, messages, failed state, auto-title;
- ``ChatEngine``          — the LangGraph pipeline that writes the answer.

The HTTP layer only translates requests and responses; the flow lives here.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.core.errors import ArgosError, InternalError, ValidationError
from app.core.observability.logs import context as log_context
from app.core.observability.telemetry import spans
from app.core.observability.telemetry.context import bind_trace, trace_attributes, trace_scope
from app.engines.chat_engine.engine import ChatEngine
from app.engines.chat_engine.outcome import ChatResult
from app.services.conversation.model import Message
from app.services.conversation.service import ConversationService
from app.services.notebook.model import ActiveSource
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatReply:
    """Everything the caller needs to show one answered message."""

    conversation_id: str
    is_new_conversation: bool
    user_message: Message
    assistant_message: Message
    result: ChatResult
    sources_used: int
    pending_sources: list[str]


class ChatOrchestrator:
    def __init__(
        self,
        notebooks: NotebookService,
        conversations: ConversationService,
        engine: ChatEngine,
    ) -> None:
        self._notebooks = notebooks
        self._conversations = conversations
        self._engine = engine

    async def send(
        self, user: CurrentUser, notebook_id: str, question: str, conversation_id: str | None = None
    ) -> ChatReply:
        """Send a message; the answer uses only the checked, ready sources."""
        active, pending = self._chat_sources(user, notebook_id)

        is_new = conversation_id is None
        if is_new:
            conversation_id = self._conversations.create_for_user(
                user_id=user.id, first_message=question, notebook_id=notebook_id
            ).id
        else:
            self._conversations.get_in_notebook(conversation_id, user.id, notebook_id)

        user_msg = self._conversations.append_user_message(
            conversation_id, user.id, question, source_snapshot=[s.version_id for s in active]
        )
        return await self._answer(
            user, conversation_id, user_msg, active, pending,
            is_new=is_new, retry=False, schedule_title=is_new,
        )

    async def retry(
        self, user: CurrentUser, notebook_id: str, conversation_id: str, message_id: str
    ) -> ChatReply:
        """Resend a failed message (reuses the same message row)."""
        active, pending = self._chat_sources(user, notebook_id)
        self._conversations.get_in_notebook(conversation_id, user.id, notebook_id)
        # Sources come from the notebook as it is NOW; the message snapshot is updated too.
        user_msg = self._conversations.prepare_retry(
            conversation_id, user.id, message_id, source_snapshot=[s.version_id for s in active]
        )
        return await self._answer(
            user, conversation_id, user_msg, active, pending,
            is_new=False,
            retry=True,
            # Auto-title only when the first message of a new conversation finally gets an answer.
            schedule_title=self._conversations.is_first_message(conversation_id, message_id),
        )

    def _chat_sources(
        self, user: CurrentUser, notebook_id: str
    ) -> tuple[list[ActiveSource], list[str]]:
        """Active sources (checked & ready) + names of sources still being processed."""
        self._notebooks.get(user, notebook_id)
        all_sources = self._notebooks.sources(user, notebook_id)
        active = self._notebooks.active_sources(user, notebook_id)
        pending = [s.display_name for s in all_sources if s.enabled and not s.is_ready]

        if not active:
            if pending:
                raise ValidationError(
                    "Checked sources are still being processed: " + ", ".join(pending) + ".",
                    code="SOURCES_PROCESSING",
                )
            raise ValidationError(
                "Check at least one ready source to start chatting.",
                code="NO_ACTIVE_SOURCES",
            )
        return active, pending

    async def _answer(
        self,
        user: CurrentUser,
        conversation_id: str,
        user_msg: Message,
        active: list[ActiveSource],
        pending: list[str],
        *,
        is_new: bool,
        retry: bool,
        schedule_title: bool,
    ) -> ChatReply:
        """One trace per answered message: chat.message → routing / sql / vector_search /
        synthesis (DESIGN_GROUP_F.md §2). Session = conversation."""
        # goes into the logs, llm_calls and every span of this trace
        log_context.bind_request(message_id=user_msg.id, session_id=conversation_id)
        with trace_scope(), spans.span("chat.message", spans.CHAIN) as root:
            spans.set_attributes(root, **{"langfuse.trace.name": "chat.message"})
            bind_trace(
                tags=["retry"] if retry else [],
                new_conversation=is_new,
                sources_used=len(active),
                pending_sources=len(pending),
            )
            spans.set_input(root, user_msg.content)
            try:
                reply = await self._run(
                    user, conversation_id, user_msg, active, pending,
                    is_new=is_new, schedule_title=schedule_title,
                )
                spans.set_output(root, {"answer": reply.result.answer, "citations": reply.result.citations})
                if reply.result.degraded:
                    bind_trace(tags=["degraded"])
                    codes = ", ".join(f"{i.component}:{i.code}" for i in reply.result.issues)
                    spans.set_warning(root, f"degraded: {codes}")
                return reply
            finally:
                # Tags/metadata collected during the run (route, degraded, …) on the root too.
                spans.set_attributes(root, **trace_attributes())

    async def _run(
        self,
        user: CurrentUser,
        conversation_id: str,
        user_msg: Message,
        active: list[ActiveSource],
        pending: list[str],
        *,
        is_new: bool,
        schedule_title: bool,
    ) -> ChatReply:
        """Run the chat for `user_msg`. On failure → the message is marked `failed` (C3)."""
        failure_ref = {"conversation_id": conversation_id, "message_id": user_msg.id}
        conversations = self._conversations
        try:
            history = conversations.get_messages_for_engine(conversation_id, user.id) or []
            result = await self._engine.chat(
                user_input=user_msg.content, history=history, sources=active
            )
            trace_id = spans.current_trace_id()
            if trace_id:
                result.trace["trace_id"] = trace_id  # "Show AI process" → open the trace in Langfuse
            bot_msg = conversations.append_assistant_message(
                conversation_id, result.answer, citations=result.citations, trace=result.trace
            )
        except ArgosError as e:
            conversations.mark_failed(user_msg.id, e.code)
            # The UI needs this ID to show the failed message + [Resend].
            e.details = {**e.details, **failure_ref}
            raise
        except asyncio.CancelledError:
            # Client disconnected / server stopping: the message must not look answered.
            conversations.mark_failed(user_msg.id, "CANCELLED")
            raise
        except Exception as e:
            logger.exception("Chat failed (message %s).", user_msg.id)
            conversations.mark_failed(user_msg.id, InternalError.code)
            raise InternalError(details=failure_ref) from e

        if schedule_title:
            conversations.schedule_auto_title(
                conversation_id=conversation_id, user_id=user.id, first_user_message=user_msg.content
            )

        return ChatReply(
            conversation_id=conversation_id,
            is_new_conversation=is_new,
            user_message=user_msg,
            assistant_message=bot_msg,
            result=result,
            sources_used=len(active),
            pending_sources=pending,
        )
