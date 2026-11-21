import logging

from openai import AsyncOpenAI

from app.core.config import app_config, secrets
from app.core.observability.ai_calls.recorder import recorder
from app.tools.speech.base import BaseSTT, STTError, STTRequest, STTResult

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

def _detected_language(data: dict) -> str | None:
    """gpt-transcribe returns ``languages: [{"code": "id"}]`` (empty when unsure);
    whisper-1 returned a single ``language``."""
    languages = data.get("languages") or []
    if languages and isinstance(languages[0], dict):
        return languages[0].get("code")
    return data.get("language")


def _duration_seconds(data: dict) -> float | None:
    usage = data.get("usage") or {}
    return usage.get("seconds") if usage.get("type") == "duration" else data.get("duration")


class OpenAISTT(BaseSTT):
    """
    STT provider using OpenAI's transcription API (model from config: gpt-transcribe).
    Docs: https://developers.openai.com/api/docs/guides/speech-to-text

    gpt-transcribe accepts only ``json``/``text`` responses (no ``verbose_json``, so no
    segment timestamps); it detects the language itself and reports the audio length in
    ``usage.seconds``.
    """

    def __init__(self):
        self._client = AsyncOpenAI(api_key=secrets.OPENAI_API_KEY)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_languages(self) -> list[str]:
        return ["*"]  # automatic language detection

    @property
    def supported_formats(self) -> list[str]:
        return ["mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "ogg", "flac"]

    async def transcribe(
            self,
            audio_bytes: bytes,
            request: STTRequest,
    ) -> STTResult:
        self.validate_language(request.language)
        model = app_config.OPENAI_TRANSCRIBE_MODEL
        if request.with_timestamps:
            logger.warning("[OpenAI STT] %s has no segment timestamps; returning text only.", model)

        ext = MIME_TO_EXT.get(request.audio_format, "webm")
        options: dict = {"response_format": "json"}
        if request.prompt:
            options["prompt"] = request.prompt
        if request.language:
            # A hint; without it the model detects the language. gpt-transcribe takes a list
            # in `languages` (instead of `language`).
            if model == "whisper-1":
                options["language"] = request.language
            else:
                options["extra_body"] = {"languages": [request.language]}

        try:
            logger.info("[OpenAI STT] Transcribing %d bytes | model=%s | lang=%s",
                        len(audio_bytes), model, request.language or "auto")
            with recorder.track("stt", model) as call:
                response = await self._client.audio.transcriptions.create(
                    model=model, file=(f"audio.{ext}", audio_bytes), **options,
                )
                data = response.model_dump()
                language = _detected_language(data)
                call.units(audio_seconds=_duration_seconds(data))
                call.content(
                    input={"language": request.language or "auto", "format": request.audio_format,
                           "audio_bytes": len(audio_bytes)},
                    output={"text": response.text, "language": language},
                )
            return STTResult(text=response.text, language=language, provider=self.provider_name)
        except Exception as e:
            logger.error(f"[OpenAI STT] Error: {e}")
            raise STTError(f"OpenAI STT failed: {e}") from e
