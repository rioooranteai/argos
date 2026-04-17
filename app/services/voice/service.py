import logging

from app.services.voice.factories.stt_factory import STTFactory
from app.services.voice.factories.tts_factory import TTSFactory
from app.services.voice.models import TTSRequest, TTSResult, STTRequest, STTResult

logger = logging.getLogger(__name__)


class VoiceService:

    def __init__(
            self,
            tts_provider: str = "openai",
            stt_provider: str = "openai_whisper",
            tts_kwargs: dict | None = None,
            stt_kwargs: dict | None = None,
    ):
        self._tts = TTSFactory.create(tts_provider, **(tts_kwargs or {}))
        self._stt = STTFactory.create(stt_provider, **(stt_kwargs or {}))
        logger.info(
            f"[VoiceService] TTS={self._tts.provider_name} | "
            f"STT={self._stt.provider_name}"
        )

    async def text_to_speech(self, request: TTSRequest) -> TTSResult:
        return await self._tts.synthesize(request)

    async def speech_to_text(
            self,
            audio_bytes: bytes,
            request: STTRequest,
    ) -> STTResult:
        return await self._stt.transcribe(audio_bytes, request)

    async def health_check(self) -> dict:
        tts_healthy = await self._tts.health_check()
        stt_healthy = await self._stt.health_check()
        return {
            "tts": {
                "provider": self._tts.provider_name,
                "healthy": tts_healthy,
                "voices": self._tts.supported_voices,
                "formats": self._tts.supported_formats,
            },
            "stt": {
                "provider": self._stt.provider_name,
                "healthy": stt_healthy,
                "languages": self._stt.supported_languages,
                "formats": self._stt.supported_formats,
            },
        }

    @property
    def available_providers(self) -> dict:
        return {
            "tts": TTSFactory.available_providers(),
            "stt": STTFactory.available_providers(),
        }
