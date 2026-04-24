import logging

from app.core.dependencies import get_nl2sql_service
from app.services.nl2sql.service import NL2SQLService
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/chat", tags=['Chat & NL2SQL'])
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    question: str = Field(..., description="Pertanyaan natural language dari user")


@router.post("/", summary="Chat dengan AI Assistant (NL2SQL)")
async def chat_with_data(
        request: ChatRequest,
        nl2sql_svc: NL2SQLService = Depends(get_nl2sql_service)
):
    """
    Endpoint interaksi pengguna.
    Menerima pertanyaan dalam bahasa natural, menerjemahkannya ke SQL,
    dan mengembalikan jawaban yang mudah dibaca.
    """

    try:
        result = await nl2sql_svc.process_query(request.question)

        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))

        return {
            "question": request.question,
            "answer": result.get("answer"),
            "metadata": {
                "generated_sql": result.get("sql_query"),
                "raw_data_count": len(result.get("raw_data") or [])
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal saat memproses pertanyaan Anda. {e}")
