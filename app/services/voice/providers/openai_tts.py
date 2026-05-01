import logging

from app.core.config import config
from app.services.voice.base.tts_base import BaseTTSProvider
from app.services.voice.exceptions import TTSError
from app.services.voice.model import TTSRequest, TTSResult
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAITTSProvider(BaseTTSProvider):
    """
    TTS Provider menggunakan OpenAI Text-to-Speech API.
    """

    def __init__(self):
        self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self._model = config.OPENAI_VOICE_MODEL

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_voices(self) -> list[str]:
        return ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    @property
    def supported_formats(self) -> list[str]:
        return ["mp3", "opus", "aac", "flac", "wav", "pcm"]

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        self.validate_voice(request.voice.value)
        self.validate_format(request.format.value)

        try:
            logger.info(
                f"[OpenAI TTS] Synthesizing {len(request.text)} chars "
                f"| voice={request.voice.value} | format={request.format.value}"
            )
            response = await self._client.audio.speech.create(
                model=self._model,
                voice=request.voice.value,
                input=request.text,
                response_format=request.format.value,
                speed=request.speed,
                instructions="Speak in a cheerful and positive tone."
            )
            return TTSResult(
                audio_bytes=response.content,
                format=request.format.value,
                character_count=len(request.text),
                provider=self.provider_name,
            )
        except Exception as e:
            logger.error(f"[OpenAI TTS] Error: {e}")
            raise TTSError(f"OpenAI TTS gagal: {e}") from e
