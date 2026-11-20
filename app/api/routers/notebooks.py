"""Notebook: sumber (maks. N, checkbox, pin versi) dan chat di dalamnya.

(DESIGN_GROUP_A.md §6, §8, §10)
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status

from app.core import log_context
from app.core.dependencies import (
    get_chat_engine,
    get_conversation_service,
    get_current_user,
    get_notebook_service,
)
from app.core.errors import ArgosError, InternalError, NotFoundError, ValidationError
from app.engines.chat_engine.engine import ChatEngine
from app.services.conversation.model import (
    ChatRequest,
    ChatResponse,
    ConversationDetailOut,
    ConversationOut,
    Message,
    MessageOut,
    RenameConversationRequest,
)
from app.services.conversation.service import ConversationService, ConversationWithMessages
from app.services.library.model import ResolvePendingRequest
from app.services.notebook.model import (
    AddSourcesRequest,
    CreateNotebookRequest,
    Notebook,
    NotebookDetailOut,
    NotebookOut,
    NotebookSource,
    NotebookSourceOut,
    RenameNotebookRequest,
    SourceUploadOut,
    UpdateSourceRequest,
)
from app.services.notebook.service import NotebookService
from app.services.user.model import CurrentUser


def _bind_notebook_to_logs(request: Request) -> None:
    """Semua log & catatan llm_calls di endpoint notebook membawa notebook_id."""
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


@router.get("", summary="Daftar notebook milik user")
def list_notebooks(
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> list[NotebookOut]:
    return [
        NotebookOut(id=nb.id, title=nb.title, source_count=count,
                    created_at=nb.created_at, updated_at=nb.updated_at)
        for nb, count in svc.list(user)
    ]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Buat notebook")
def create_notebook(
    body: CreateNotebookRequest = CreateNotebookRequest(),
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> NotebookDetailOut:
    nb = svc.create(user, body.title)
    return _detail(nb, [], svc.max_sources)


@router.get("/{notebook_id}", summary="Detail notebook beserta sumbernya")
def get_notebook(
    notebook_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> NotebookDetailOut:
    nb = svc.get(user, notebook_id)
    return _detail(nb, svc.sources(user, notebook_id), svc.max_sources)


@router.patch("/{notebook_id}", summary="Ganti judul notebook")
def rename_notebook(
    notebook_id: str,
    body: RenameNotebookRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> NotebookDetailOut:
    nb = svc.rename(user, notebook_id, body.title)
    return _detail(nb, svc.sources(user, notebook_id), svc.max_sources)


@router.delete("/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Hapus notebook")
def delete_notebook(
    notebook_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> Response:
    svc.delete(user, notebook_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Sumber ───────────────────────────────────────────────────────────────


@router.post("/{notebook_id}/sources", summary="Tambah sumber dari Library")
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
    summary="Upload dokumen ke Library dan langsung pasang ke notebook",
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
    summary="Upload yang mirip dokumen Library: pilih versi baru / dokumen terpisah, lalu pasang",
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


@router.patch("/{notebook_id}/sources/{document_id}", summary="Centang/hapus centang atau pakai versi terbaru")
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


@router.delete("/{notebook_id}/sources/{document_id}", summary="Lepas sumber dari notebook")
def remove_source(
    notebook_id: str,
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: NotebookService = Depends(get_notebook_service),
) -> list[NotebookSourceOut]:
    return _sources_out(svc.remove_source(user, notebook_id, document_id))


# ── Percakapan ───────────────────────────────────────────────────────────


def _conversation_in_notebook(
    conv_svc: ConversationService, conversation_id: str, user: CurrentUser, notebook_id: str
) -> ConversationWithMessages:
    bundle = conv_svc.get_with_messages(conversation_id, user.id)
    if bundle is None or bundle.conversation.notebook_id != notebook_id:
        raise NotFoundError("Percakapan tidak ditemukan.")
    return bundle


@router.get("/{notebook_id}/conversations", summary="Daftar percakapan di notebook")
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


@router.get("/{notebook_id}/conversations/{conversation_id}", summary="Percakapan beserta pesannya")
def get_conversation(
    notebook_id: str,
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailOut:
    nb_svc.get(user, notebook_id)
    bundle = _conversation_in_notebook(conv_svc, conversation_id, user, notebook_id)
    c = bundle.conversation
    return ConversationDetailOut(
        id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
        messages=[
            MessageOut.from_message(m) for m in bundle.messages
        ],
    )


@router.patch("/{notebook_id}/conversations/{conversation_id}", summary="Ganti judul percakapan")
def rename_conversation(
    notebook_id: str,
    conversation_id: str,
    body: RenameConversationRequest,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> ConversationOut:
    nb_svc.get(user, notebook_id)
    _conversation_in_notebook(conv_svc, conversation_id, user, notebook_id)
    conv_svc.rename(conversation_id, user.id, body.title)
    c = _conversation_in_notebook(conv_svc, conversation_id, user, notebook_id).conversation
    return ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)


@router.delete(
    "/{notebook_id}/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus percakapan",
)
def delete_conversation(
    notebook_id: str,
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
) -> Response:
    nb_svc.get(user, notebook_id)
    _conversation_in_notebook(conv_svc, conversation_id, user, notebook_id)
    conv_svc.delete(conversation_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notebook_id}/messages", summary="Kirim pesan; jawaban hanya dari sumber yang dicentang")
async def send_message(
    notebook_id: str,
    request: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    nb_svc: NotebookService = Depends(get_notebook_service),
    conv_svc: ConversationService = Depends(get_conversation_service),
    chat_engine: ChatEngine = Depends(get_chat_engine),
) -> ChatResponse:
    active, pending = _chat_sources(nb_svc, user, notebook_id)

    is_new = request.conversation_id is None
    if is_new:
        conversation_id = conv_svc.create_for_user(
            user_id=user.id, first_message=request.question, notebook_id=notebook_id
        ).id
    else:
        conversation_id = request.conversation_id
        _conversation_in_notebook(conv_svc, conversation_id, user, notebook_id)

    snapshot = [s.version_id for s in active]
    user_msg = conv_svc.append_user_message(
        conversation_id, user.id, request.question, source_snapshot=snapshot
    )
    return await _answer(
        conv_svc, chat_engine, user, conversation_id, user_msg, active, pending,
        is_new=is_new, schedule_title=is_new,
    )


def _chat_sources(nb_svc: NotebookService, user: CurrentUser, notebook_id: str):
    """Sumber aktif (dicentang & ready) + nama sumber yang masih diproses."""
    nb_svc.get(user, notebook_id)
    all_sources = nb_svc.sources(user, notebook_id)
    active = nb_svc.active_sources(user, notebook_id)
    pending = [s.display_name for s in all_sources if s.enabled and not s.is_ready]

    if not active:
        if pending:
            raise ValidationError(
                "Sumber yang dicentang masih diproses: " + ", ".join(pending) + ".",
                code="SOURCES_PROCESSING",
            )
        raise ValidationError(
            "Centang minimal satu sumber yang sudah siap untuk memulai chat.",
            code="NO_ACTIVE_SOURCES",
        )
    return active, pending


async def _answer(
    conv_svc: ConversationService,
    chat_engine: ChatEngine,
    user: CurrentUser,
    conversation_id: str,
    user_msg: Message,
    active: list,
    pending: list[str],
    *,
    is_new: bool,
    schedule_title: bool,
) -> ChatResponse:
    """Jalankan chat untuk `user_msg`. Gagal → pesan ditandai `failed` (C3)."""
    log_context.bind_request(message_id=user_msg.id)  # ikut ke log & llm_calls
    failure_ref = {"conversation_id": conversation_id, "message_id": user_msg.id}
    try:
        history = conv_svc.get_messages_for_engine(conversation_id, user.id) or []
        result = await chat_engine.chat(user_input=user_msg.content, history=history, sources=active)
        bot_msg = conv_svc.append_assistant_message(
            conversation_id, result.answer, citations=result.citations, trace=result.trace
        )
    except ArgosError as e:
        conv_svc.mark_failed(user_msg.id, e.code)
        # UI butuh ID ini untuk menampilkan pesan gagal + [Kirim ulang].
        e.details = {**e.details, **failure_ref}
        raise
    except asyncio.CancelledError:
        # Klien memutus koneksi / server berhenti: pesan tidak boleh tampak terjawab.
        conv_svc.mark_failed(user_msg.id, "CANCELLED")
        raise
    except Exception as e:
        logger.exception("Chat gagal (pesan %s).", user_msg.id)
        conv_svc.mark_failed(user_msg.id, InternalError.code)
        raise InternalError(details=failure_ref) from e

    if schedule_title:
        conv_svc.schedule_auto_title(
            conversation_id=conversation_id, user_id=user.id, first_user_message=user_msg.content
        )

    return ChatResponse(
        conversation_id=conversation_id,
        question=user_msg.content,
        answer=result.answer,
        citations=result.citations,
        metadata={
            "route": result.route,
            "router_reasoning": result.router_reasoning,
            "is_new_conversation": is_new,
            "sources_used": len(active),
            "pending_sources": pending,
            "degraded": result.degraded,
            "issues": [i.to_dict() for i in result.issues],
            "trace": result.trace,
            "user_message_id": user_msg.id,
            "assistant_message_id": bot_msg.id,
        },
    )
