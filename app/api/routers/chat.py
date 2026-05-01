from __future__ import annotations

import logging

from app.core.dependencies import (
    get_chat_engine,
    get_conversation_service,
    get_current_user,
)
from app.engines.chat_engine.engine import ChatEngine
from app.services.conversation.model import (
    ConversationOut,
    CreateConversationRequest,
    ConversationDetailOut,
    ChatRequest,
    MessageOut,
    ChatResponse,
    RenameConversationRequest
)
from app.services.conversation.service import ConversationService
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])
logger = logging.getLogger(__name__)


@router.get("/conversations", summary="List user's conversations")
async def list_conversations(
        user: dict = Depends(get_current_user),
        svc: ConversationService = Depends(get_conversation_service),
) -> list[ConversationOut]:
    convs = svc.list_for_user(user_id=user["sub"])
    return [
        ConversationOut(
            id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at
        )
        for c in convs
    ]


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation",
)
async def create_conversation(
        body: CreateConversationRequest = CreateConversationRequest(),
        user: dict = Depends(get_current_user),
        svc: ConversationService = Depends(get_conversation_service),
) -> ConversationOut:
    conv = svc.create_for_user(user_id=user["sub"], first_message=body.title)
    return ConversationOut(
        id=conv.id, title=conv.title, created_at=conv.created_at, updated_at=conv.updated_at
    )


@router.get(
    "/conversations/{conversation_id}",
    summary="Get conversation with full message history",
)
async def get_conversation(
        conversation_id: str,
        user: dict = Depends(get_current_user),
        svc: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailOut:
    bundle = svc.get_with_messages(conversation_id, user["sub"])
    if bundle is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return ConversationDetailOut(
        id=bundle.conversation.id,
        title=bundle.conversation.title,
        created_at=bundle.conversation.created_at,
        updated_at=bundle.conversation.updated_at,
        messages=[
            MessageOut(
                id=m.id, role=m.role, content=m.content, created_at=m.created_at
            )
            for m in bundle.messages
        ],
    )


@router.patch(
    "/conversations/{conversation_id}",
    summary="Rename a conversation",
)
async def rename_conversation(
        conversation_id: str,
        body: RenameConversationRequest,
        user: dict = Depends(get_current_user),
        svc: ConversationService = Depends(get_conversation_service),
) -> ConversationOut:
    ok = svc.rename(conversation_id, user["sub"], body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    bundle = svc.get_with_messages(conversation_id, user["sub"])
    # Defensive — bundle should exist since rename succeeded.
    if bundle is None:  # pragma: no cover
        raise HTTPException(status_code=404, detail="Conversation not found.")
    c = bundle.conversation
    return ConversationOut(
        id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
)
async def delete_conversation(
        conversation_id: str,
        user: dict = Depends(get_current_user),
        svc: ConversationService = Depends(get_conversation_service),
) -> None:
    ok = svc.delete(conversation_id, user["sub"])
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return None


# ── Send a message ─────────────────────────────────────────────────────────


@router.post("/", summary="Send a message in a conversation")
async def chat_with_data(
        request: ChatRequest,
        chat_engine: ChatEngine = Depends(get_chat_engine),
        svc: ConversationService = Depends(get_conversation_service),
        user: dict = Depends(get_current_user),
) -> ChatResponse:
    """Send a message.

    - If `conversation_id` is null, a new conversation is created (titled with a
      truncated form of `question`) and its ID is returned. An LLM auto-title
      task is scheduled in the background; the returned title may be stale on
      this first response — clients should refetch the conversation list after
      receiving the answer.
    - Otherwise the message is appended to the existing conversation. 404 if
      the user doesn't own it.
    """
    user_id = user["sub"]
    is_new_conversation = request.conversation_id is None

    # Resolve / create conversation.
    if is_new_conversation:
        conv = svc.create_for_user(user_id=user_id, first_message=request.question)
        conversation_id = conv.id
    else:
        conversation_id = request.conversation_id
        if svc.get_with_messages(conversation_id, user_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

    # 1. Persist user message FIRST so it shows up in history even if the
    #    LLM call fails partway through.
    user_msg = svc.append_user_message(conversation_id, user_id, request.question)
    if user_msg is None:
        # Should be unreachable — we just created/verified the conversation.
        raise HTTPException(status_code=404, detail="Conversation not found.")

    # 2. Load full history (already includes the user message we just saved)
    history = svc.get_messages_for_engine(conversation_id, user_id) or []

    # 3. Run the LangGraph pipeline.
    try:
        result = await chat_engine.chat(
            user_input=request.question,
            history=history,
        )
    except Exception:
        logger.exception("Chat engine failure (conversation=%s).", conversation_id)
        raise HTTPException(status_code=500, detail="Chat engine error.")

    if result.get("error"):
        # User-facing error from the graph (e.g. NL2SQL refusal). We still
        # leave the user message persisted so the user can see what they asked.
        raise HTTPException(status_code=400, detail=result["error"])

    answer = result["answer"]

    # 4. Persist assistant response.
    svc.append_assistant_message(conversation_id, answer)

    # 5. Schedule auto-title for new conversations (best-effort, async).
    if is_new_conversation:
        svc.schedule_auto_title(
            conversation_id=conversation_id,
            user_id=user_id,
            first_user_message=request.question,
        )

    return ChatResponse(
        conversation_id=conversation_id,
        question=request.question,
        answer=answer,
        metadata={
            "route": result["route"],
            "router_reasoning": result["router_reasoning"],
            "is_new_conversation": is_new_conversation,
        },
    )
