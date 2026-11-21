"""Notebooks: sources (max. N, checkbox, pinned version) and the chat inside them.

(DESIGN_GROUP_A.md §6, §8, §10)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status

from app.api.dependencies import (
    get_chat_orchestrator,
    get_conversation_service,
    get_current_user,
    get_notebook_service,
    rate_limit,
)
from app.api.schemas.conversation import (
    ChatRequest,
    ChatResponse,
    ConversationDetailOut,
    ConversationOut,
    MessageOut,
    RenameConversationRequest,
)
from app.api.schemas.library import ResolvePendingRequest
from app.api.schemas.notebook import (
    AddSourcesRequest,
    CreateNotebookRequest,
    NotebookDetailOut,
    NotebookOut,
    NotebookSourceOut,
    RenameNotebookRequest,
    SourceUploadOut,
    UpdateSourceRequest,
)
from app.core import log_context
from app.engines.chat_engine.orchestrator import ChatOrchestrator, ChatReply
from app.services.conversation.service import ConversationService
from app.services.notebook.model import Notebook, NotebookSource
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser


def _bind_notebook_to_logs(request: Request) -> None:
    """Every log line & llm_calls record in the notebook endpoints carries notebook_id."""
    log_context.bind_request(notebook_id=request.path_params.get("notebook_id"))


router = APIRouter(
    prefix="/api/v1/notebooks",
    tags=["Notebook"],
    dependencies=[Depends(_bind_notebook_to_logs)],
)
logger = logging.getLogger(__name__)


def _detail(nb: Notebook, sources: list[NotebookSource], max_sources: int) -> NotebookDetailOut:
    return NotebookDetailOut(
        id=nb.id,
        title=nb.title,
        source_count=len(sources),
        created_at=nb.created_at,
        updated_at=nb.updated_at,
        max_sources=max_sources,
        sources=[NotebookSourceOut.from_source(s) for s in sources],
    )


def _sources_out(sources: list[NotebookSource]) -> list[NotebookSourceOut]:
    return [NotebookSourceOut.from_source(s) for s in sources]


# ── Notebook ─────────────────────────────────────────────────────────────


@router.get("", summary="List the user's notebooks")
def list_notebooks(
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> list[NotebookOut]:
    return [
        NotebookOut(id=nb.id, title=nb.title, source_count=count,
                    created_at=nb.created_at, updated_at=nb.updated_at,
                    last_opened_at=nb.last_opened_at)
        for nb, count in svc.list(user)
    ]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a notebook")
def create_notebook(
    body: CreateNotebookRequest = CreateNotebookRequest(),
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> NotebookDetailOut:
    nb = svc.create(user, body.title)
    return _detail(nb, [], svc.max_sources)


@router.get("/{notebook_id}", summary="Notebook details with its sources")
def get_notebook(
    notebook_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> NotebookDetailOut:
    nb = svc.open(user, notebook_id)  # recorded as the last opened notebook
    return _detail(nb, svc.sources(user, notebook_id), svc.max_sources)


@router.patch("/{notebook_id}", summary="Rename a notebook")
def rename_notebook(
    notebook_id: str,
    body: RenameNotebookRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> NotebookDetailOut:
    nb = svc.rename(user, notebook_id, body.title)
    return _detail(nb, svc.sources(user, notebook_id), svc.max_sources)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a notebook")
def delete_notebook(
    notebook_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> Response:
    svc.delete(user, notebook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Sources ──────────────────────────────────────────────────────────────


@router.post("/{notebook_id}/sources", summary="Add a source from the Library")
def add_sources(
    notebook_id: str,
    body: AddSourcesRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> list[NotebookSourceOut]:
    return _sources_out(svc.add_from_library(user, notebook_id, body.document_ids))


@router.post(
    "/{notebook_id}/sources/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload documents to the Library and add them to the notebook",
    dependencies=[Depends(rate_limit("upload"))],
)
async def upload_sources(
    notebook_id: str,
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> SourceUploadOut:
    results, sources = await svc.upload(user, notebook_id, files)
    return SourceUploadOut(results=results, sources=_sources_out(sources))


@router.post(
    "/{notebook_id}/sources/pending/{pending_id}/resolve",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload similar to a Library document: choose new version / separate document, then add it",
    dependencies=[Depends(rate_limit("upload"))],
)
async def resolve_pending_source(
    notebook_id: str,
    pending_id: str,
    body: ResolvePendingRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> SourceUploadOut:
    result, sources = await svc.resolve_pending(user, notebook_id, pending_id, body.action)
    return SourceUploadOut(results=[result], sources=_sources_out(sources))


@router.patch("/{notebook_id}/sources/{document_id}", summary="Check/uncheck a source or switch to the latest version")
def update_source(
    notebook_id: str,
    document_id: str,
    body: UpdateSourceRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> list[NotebookSourceOut]:
    return _sources_out(
        svc.update_source(user, notebook_id, document_id, body.enabled, body.use_latest_version)
    )


@router.delete("/{notebook_id}/sources/{document_id}", summary="Remove a source from the notebook")
def remove_source(
    notebook_id: str,
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> list[NotebookSourceOut]:
    return _sources_out(svc.remove_source(user, notebook_id, document_id))


# ── Conversations ────────────────────────────────────────────────────────


@router.get("/{notebook_id}/conversations", summary="List the conversations in a notebook")
def list_conversations(
    notebook_id: str,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> list[ConversationOut]:
    nb_svc.get(user, notebook_id)
    return [
        ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)
        for c in conv_svc.list_for_notebook(user.id, notebook_id)
    ]


@router.get("/{notebook_id}/conversations/{conversation_id}", summary="A conversation with its messages")
def get_conversation(
    notebook_id: str,
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailOut:
    nb_svc.get(user, notebook_id)
    bundle = conv_svc.get_in_notebook(conversation_id, user.id, notebook_id)
    c = bundle.conversation
    return ConversationDetailOut(
        id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
        messages=[
            MessageOut.from_message(m) for m in bundle.messages
        ],
    )


@router.patch("/{notebook_id}/conversations/{conversation_id}", summary="Rename a conversation")
def rename_conversation(
    notebook_id: str,
    conversation_id: str,
    body: RenameConversationRequest,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> ConversationOut:
    nb_svc.get(user, notebook_id)
    conv_svc.get_in_notebook(conversation_id, user.id, notebook_id)
    conv_svc.rename(conversation_id, user.id, body.title)
    c = conv_svc.get_in_notebook(conversation_id, user.id, notebook_id).conversation
    return ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)


@router.delete(
    "/{notebook_id}/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
)
def delete_conversation(
    notebook_id: str,
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> Response:
    nb_svc.get(user, notebook_id)
    conv_svc.get_in_notebook(conversation_id, user.id, notebook_id)
    conv_svc.delete(conversation_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{notebook_id}/messages",
    summary="Send a message; the answer uses only the checked sources",
    dependencies=[Depends(rate_limit("chat"))],
)
async def send_message(
    notebook_id: str,
    request: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    chat: ChatOrchestrator = Depends(get_chat_orchestrator),
) -> ChatResponse:
    reply = await chat.send(user, notebook_id, request.question, request.conversation_id)
    return _chat_response(reply)


@router.post(
    "/{notebook_id}/conversations/{conversation_id}/messages/{message_id}/retry",
    summary="Resend a failed message (reuses the same message row)",
    dependencies=[Depends(rate_limit("chat"))],
)
async def retry_message(
    notebook_id: str,
    conversation_id: str,
    message_id: str,
    user: CurrentUser = Depends(get_current_user),
    chat: ChatOrchestrator = Depends(get_chat_orchestrator),
) -> ChatResponse:
    reply = await chat.retry(user, notebook_id, conversation_id, message_id)
    return _chat_response(reply)


def _chat_response(reply: ChatReply) -> ChatResponse:
    result = reply.result
    return ChatResponse(
        conversation_id=reply.conversation_id,
        question=reply.user_message.content,
        answer=result.answer,
        citations=result.citations,
        metadata={
            "route": result.route,
            "router_reasoning": result.router_reasoning,
            "is_new_conversation": reply.is_new_conversation,
            "sources_used": reply.sources_used,
            "pending_sources": reply.pending_sources,
            "degraded": result.degraded,
            "issues": [i.to_dict() for i in result.issues],
            "trace": result.trace,
            "user_message_id": reply.user_message.id,
            "assistant_message_id": reply.assistant_message.id,
        },
    )
