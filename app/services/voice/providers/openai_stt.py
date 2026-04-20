import logging
import io

from app.core.config import config
from app.services.voice.base.stt_base import BaseSTTProvider
from app.services.voice.exceptions import STTError
from app.services.voice.models import STTRequest, STTResult, STTSegment
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

MIME_TO_EXT = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
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
}

class OpenAISTTProvider(BaseSTTProvider):
    """
    STT Provider menggunakan OpenAI Whisper API (cloud).
    Model  : whisper-1
    Biaya  : $0.006 per menit audio
    Docs   : https://platform.openai.com/docs/guides/speech-to-text
    """

    def __init__(self):
        self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    @property
    def provider_name(self) -> str:
        return "openai_whisper"

    @property
    def supported_languages(self) -> list[str]:
        # Whisper API support 57 bahasa, return ['*'] untuk semua
        return ["*"]

    @property
    def supported_formats(self) -> list[str]:
        return ["mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "ogg", "flac"]

    async def transcribe(
            self,
            audio_bytes: bytes,
            request: STTRequest,
    ) -> STTResult:
        self.validate_language(request.language)

        try:
            logger.info(
                f"[OpenAI STT] Transcribing {len(audio_bytes)} bytes "
                f"| lang={request.language} | timestamps={request.with_timestamps}"
            )

            ext = MIME_TO_EXT.get(request.audio_format, "webm")
            filename = f"audio.{ext}"

            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename

            if request.with_timestamps:
                response = await self._client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=request.language,
                    prompt=request.prompt,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
                segments = [
                    STTSegment(
                        start=round(s.start, 2),
                        end=round(s.end, 2),
                        text=s.text.strip(),
                    )
                    for s in (response.segments or [])
                ]
                return STTResult(
                    text=response.text,
                    language=response.language,
                    segments=segments,
                    provider=self.provider_name,
                )
            else:
                response = await self._client.audio.transcriptions.create(
                    model="whisper-1",
                    file=(filename, audio_bytes),
                    language=request.language,
                    prompt=request.prompt,
                )
                return STTResult(
                    text=response.text,
                    provider=self.provider_name,
                )

        except Exception as e:
            logger.error(f"[OpenAI STT] Error: {e}")
            raise STTError(f"OpenAI STT gagal: {e}") from e

    async def health_check(self) -> bool:
        try:
            await self._client.models.retrieve("whisper-1")
            return True
        except Exception as e:
            logger.warning(f"[OpenAI STT] Health check gagal: {e}")
            return False
