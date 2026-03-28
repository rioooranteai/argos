import logging
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

# Import dari dependencies yang benar!
from app.api.dependencies import get_nl2sql_service
from app.services.nl2sql.service import NL2SQLService

router = APIRouter()
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
    logger.info(f"User bertanya: {request.question}")

    try:
        result = await nl2sql_svc.process_query(request.question)

        # Jika sistem keamanan menangkap adanya pelanggaran
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
        logger.error(f"Gagal memproses chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Terjadi kesalahan internal saat memproses pertanyaan Anda.")