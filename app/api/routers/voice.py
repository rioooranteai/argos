import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import app_config
from app.api.dependencies import get_current_user, get_voice_service
from app.core.errors import PayloadTooLarge, UnsupportedMediaType, UpstreamError, ValidationError
from app.core.rate_limit import rate_limit
from app.services.voice.service import VoiceService
from app.tools.speech.base import (
    SpeechError,
    STTRequest,
    TTSRequest,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)

logger = logging.getLogger(__name__)

# Sign-in required: STT/TTS spend OpenAI credit (audit point 4, DESIGN_GROUP_D.md D4).
router = APIRouter(
    prefix="/api/v1/voice",
    tags=["Voice"],
    dependencies=[Depends(get_current_user), Depends(rate_limit("voice"))],
)

ALLOWED_AUDIO = {
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/ogg",
    "audio/oga",
    "audio/flac",
    "audio/x-flac",
    "audio/m4a",
    "audio/x-m4a",
    "video/mp4",
    "video/webm",
    "application/octet-stream",
}

MIME_TO_EXT = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "video/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/oga": "oga",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "application/octet-stream": "webm",
}


@contextmanager
def _voice_errors() -> Iterator[None]:
    """Voice service errors → the standard error contract (DESIGN_GROUP_C.md §2)."""
    try:
        yield
    except (UnsupportedFormatError, UnsupportedLanguageError) as e:
        raise ValidationError(str(e), code="VOICE_UNSUPPORTED") from e
    except SpeechError as e:
        # OpenAI details only go to the log (the global handler logs 5xx errors with the stack).
        raise UpstreamError(
            "The voice service is unavailable right now. Try again shortly.", code="VOICE_UNAVAILABLE"
        ) from e


@router.post("/stt")
async def speech_to_text(
        audio: UploadFile = File(...),
        language: str | None = Query(default=None),  # None = Whisper detects the language
        with_timestamps: bool = Query(default=False),
        voice_service: VoiceService = Depends(get_voice_service),
):
    content_type = audio.content_type or "application/octet-stream"

    if content_type not in ALLOWED_AUDIO:
        raise UnsupportedMediaType("Unsupported audio format.", code="AUDIO_UNSUPPORTED")

    # Read in chunks & stopped as soon as it goes over the limit (DESIGN_GROUP_B.md §8);
    # the limit follows the Whisper API (25 MB).
    max_bytes = app_config.STT_MAX_MB * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while chunk := await audio.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise PayloadTooLarge(f"Audio is larger than {app_config.STT_MAX_MB} MB.", code="AUDIO_TOO_LARGE")
        chunks.append(chunk)
    audio_bytes = b"".join(chunks)

    if not audio_bytes:
        raise ValidationError("The audio file is empty.", code="AUDIO_EMPTY")

    ext = MIME_TO_EXT.get(content_type, "webm")

    request = STTRequest(
        language=language,
        with_timestamps=with_timestamps,
        audio_format=content_type,
        audio_filename=f"audio.{ext}",
    )

    with _voice_errors():
        return await voice_service.speech_to_text(audio_bytes, request)


@router.post("/tts")
async def text_to_speech(
        request: TTSRequest,
        voice_service: VoiceService = Depends(get_voice_service),
):
    with _voice_errors():
        result = await voice_service.text_to_speech(request)

    return StreamingResponse(
        io.BytesIO(result.audio_bytes),
        media_type=f"audio/{result.format}",
    )
