"""Voice use cases: speech-to-text for chat input, text-to-speech for answers."""
from __future__ import annotations

import logging

from app.tools.speech.base import BaseSTT, BaseTTS, STTRequest, STTResult, TTSRequest, TTSResult

logger = logging.getLogger(__name__)


class VoiceService:
    def __init__(self, stt: BaseSTT, tts: BaseTTS) -> None:
        self._stt = stt
        self._tts = tts
        logger.info("[VoiceService] TTS=%s | STT=%s", tts.provider_name, stt.provider_name)

    async def text_to_speech(self, request: TTSRequest) -> TTSResult:
        return await self._tts.synthesize(request)

    async def speech_to_text(self, audio_bytes: bytes, request: STTRequest) -> STTResult:
        return await self._stt.transcribe(audio_bytes, request)
