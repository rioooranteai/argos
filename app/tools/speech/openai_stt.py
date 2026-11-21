import io
import logging

from openai import AsyncOpenAI

from app.core.config import app_config, secrets
from app.core.observability.recorder import recorder
from app.tools.speech.base import BaseSTT, STTError, STTRequest, STTResult, STTSegment

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

def _report(call, request: STTRequest, audio_bytes: bytes, response) -> None:
    """Audio length (for pricing) and the transcript for the trace; never the audio itself."""
    call.units(audio_seconds=getattr(response, "duration", None))
    call.content(
        input={"language": request.language or "auto", "format": request.audio_format,
               "audio_bytes": len(audio_bytes)},
        output={"text": response.text, "language": getattr(response, "language", None)},
    )


class OpenAISTT(BaseSTT):
    """
    STT provider using the OpenAI Whisper API (cloud).
    Model  : whisper-1
    Cost   : $0.006 per minute of audio
    Docs   : https://platform.openai.com/docs/guides/speech-to-text
    """

    def __init__(self):
        self._client = AsyncOpenAI(api_key=secrets.OPENAI_API_KEY)

    @property
    def provider_name(self) -> str:
        return "openai_whisper"

    @property
    def supported_languages(self) -> list[str]:
        # The Whisper API supports 57 languages; return ['*'] for all
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
        self._model = app_config.OPENAI_TRANSCRIBE_MODEL

        try:
            logger.info(
                f"[OpenAI STT] Transcribing {len(audio_bytes)} bytes "
                f"| lang={request.language} | timestamps={request.with_timestamps}"
            )

            ext = MIME_TO_EXT.get(request.audio_format, "webm")
            filename = f"audio.{ext}"

            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename

            # Only send language/prompt when set: without `language` Whisper detects it.
            optional = {
                k: v for k, v in (("language", request.language), ("prompt", request.prompt))
                if v is not None
            }

            if request.with_timestamps:
                with recorder.track("stt", self._model) as call:
                    response = await self._client.audio.transcriptions.create(
                        model=self._model,
                        file=audio_file,
                        response_format="verbose_json",
                        timestamp_granularities=["segment"],
                        **optional,
                    )
                    _report(call, request, audio_bytes, response)
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
                with recorder.track("stt", "whisper-1") as call:
                    response = await self._client.audio.transcriptions.create(
                        model="whisper-1",
                        file=(filename, audio_bytes),
                        response_format="verbose_json",  # includes the detected language
                        **optional,
                    )
                    _report(call, request, audio_bytes, response)
                return STTResult(
                    text=response.text,
                    language=getattr(response, "language", None),
                    provider=self.provider_name,
                )

        except Exception as e:
            logger.error(f"[OpenAI STT] Error: {e}")
            raise STTError(f"OpenAI STT failed: {e}") from e
