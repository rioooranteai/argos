import io
import logging

from app.core.dependencies import get_voice_service
from app.services.voice.models import STTRequest, TTSRequest
from app.services.voice.service import VoiceService
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["Voice"])

ALLOWED_AUDIO = {"audio/wav", "audio/webm", "audio/mpeg", "audio/ogg"}


@router.post("/stt")
async def speech_to_text(
        audio: UploadFile = File(...),
        language: str = Query(default="id"),
        with_timestamps: bool = Query(default=False),
        voice_service: VoiceService = Depends(get_voice_service),
):
    if audio.content_type not in ALLOWED_AUDIO:
        raise HTTPException(status_code=415, detail="Format audio tidak didukung")

    audio_bytes = await audio.read()

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="File kosong")

    request = STTRequest(
        language=language,
        with_timestamps=with_timestamps,
        audio_format=audio.content_type,
    )

    return await voice_service.speech_to_text(audio_bytes, request)


@router.post("/tts")
async def text_to_speech(
        request: TTSRequest,
        voice_service: VoiceService = Depends(get_voice_service),
):
    result = await voice_service.text_to_speech(request)

    return StreamingResponse(
        io.BytesIO(result.audio_bytes),
        media_type=f"audio/{result.format}",
    )
