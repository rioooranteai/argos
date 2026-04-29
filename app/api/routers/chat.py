import logging

from app.core.dependencies import get_chat_engine, get_current_user
from app.engines.chat_engine.engine import ChatEngine
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    question: str = Field(..., description="Pertanyaan natural language dari user")
    session_id: str = Field(default="default", description="ID sesi untuk isolasi history per user")


class ChatResponse(BaseModel):
    question: str
    answer: str
    metadata: dict


@router.post("/", summary="Chat dengan AI Assistant (SQL + Vector)")
async def chat_with_data(
        request: ChatRequest,
        chat_engine: ChatEngine = Depends(get_chat_engine),
        user: dict = Depends(get_current_user),
):
    """
    Endpoint chat utama.
    LangGraph akan otomatis memutuskan apakah menjawab dari SQL, Vector Store, atau keduanya.
    """
    try:
        # Isolasi history per user — gabungkan user ID dengan session_id
        scoped_session_id = f"{user['sub']}:{request.session_id}"

        result = await chat_engine.chat(
            user_input=request.question,
            session_id=scoped_session_id,
        )

        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        return ChatResponse(
            question=request.question,
            answer=result["answer"],
            metadata={
                "route": result["route"],
                "router_reasoning": result["router_reasoning"],
                "session_id": request.session_id,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Kesalahan tidak terduga di endpoint chat")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}/history", summary="Reset conversation history")
async def clear_history(
        session_id: str,
        chat_engine: ChatEngine = Depends(get_chat_engine),
        user: dict = Depends(get_current_user),
):
    """Hapus conversation history untuk sesi tertentu."""
    chat_engine.clear_history(f"{user['sub']}:{session_id}")
    return {"status": "ok", "message": f"History sesi '{session_id}' berhasil dihapus."}


@router.get("/{session_id}/history", summary="Lihat conversation history")
async def get_history(
        session_id: str,
        chat_engine: ChatEngine = Depends(get_chat_engine),
        user: dict = Depends(get_current_user),
):
    """Ambil conversation history untuk sesi tertentu."""
    history = chat_engine.get_history(f"{user['sub']}:{session_id}")
    return {"session_id": session_id, "messages": history}
