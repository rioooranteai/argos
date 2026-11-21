"""Speech contract: speech-to-text (``BaseSTT``) and text-to-speech (``BaseTTS``)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, Field


class VoiceType(str, Enum):
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    NOVA = "nova"
    SHIMMER = "shimmer"


class AudioFormat(str, Enum):
    MP3 = "mp3"
    WAV = "wav"
    OPUS = "opus"
    FLAC = "flac"
    AAC = "aac"
    PCM = "pcm"


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: VoiceType = VoiceType.ALLOY
    format: AudioFormat = AudioFormat.MP3
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


class TTSResult(BaseModel):
    audio_bytes: bytes
    format: str
    character_count: int
    provider: str


class STTRequest(BaseModel):
    language: str | None = Field(
        default=None, description="ISO 639-1 code, e.g. 'id', 'en'. None = detect automatically"
    )
    prompt: str | None = Field(default=None, description="Context hint to improve accuracy")
    audio_format: str = Field(default="webm", description="Audio format: wav, webm, mp3, etc.")
    with_timestamps: bool = False


class STTSegment(BaseModel):
    start: float
    end: float
    text: str


class STTResult(BaseModel):
    text: str
    language: str | None = None
    language_probability: float | None = None
    segments: list[STTSegment] = []
    provider: str


class SpeechError(Exception):
    """Base exception for every speech (STT/TTS) error."""


class TTSError(SpeechError):
    """Error during Text-to-Speech."""


class STTError(SpeechError):
    """Error during Speech-to-Text."""


class UnsupportedFormatError(SpeechError):
    """The audio format is not supported by the provider."""

    def __init__(self, fmt: str, provider: str, supported: list[str]):
        super().__init__(
            f"Format '{fmt}' is not supported by {provider}. "
            f"Supported formats: {', '.join(supported)}"
        )


class UnsupportedLanguageError(SpeechError):
    """The language is not supported by the provider."""

    def __init__(self, language: str, provider: str, supported: list[str]):
        super().__init__(
            f"Language '{language}' is not supported by {provider}. "
            f"Supported languages: {', '.join(supported)}"
        )


class ProviderUnavailableError(SpeechError):
    """The provider cannot be reached / its health check failed."""

    def __init__(self, provider: str, reason: str = ""):
        super().__init__(
            f"Provider '{provider}' is unavailable. {reason}".strip()
        )


class BaseSTT(ABC):
    """
    The required contract for every STT provider.

    Every provider that inherits this class MUST implement every
    abstract method/property below. Otherwise Python raises
    TypeError when the provider is instantiated.

    How to add a new provider:
        1. Create a new file in providers/
        2. Inherit BaseSTT
        3. Implement every method below
        4. Add a branch in app/tools/factory.py
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Unique provider identifier.
        Example: 'whisper', 'google', 'deepgram', 'azure'
        """
        ...

    @property
    @abstractmethod
    def supported_languages(self) -> list[str]:
        """
        Supported ISO 639-1 language codes.
        Example: ['id', 'en', 'zh', 'ja']
        Return ['*'] if the provider supports every language.
        """
        ...

    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """
        Accepted input audio formats.
        Example: ['mp3', 'wav', 'ogg', 'flac', 'webm']
        """
        ...

    @abstractmethod
    async def transcribe(
            self,
            audio_bytes: bytes,
            request: STTRequest,
    ) -> STTResult:
        """
        Convert audio bytes to text.

        Args:
            audio_bytes : Raw bytes of the audio file
            filename    : Original file name (used to detect the extension)
            request     : STTRequest with language, prompt, with_timestamps

        Returns:
            STTResult with text, language, probability, segments, provider

        Raises:
            STTError: if transcription fails
            UnsupportedLanguageError: if the language is not supported
            UnsupportedFormatError: if the format is not supported
        """
        ...


    def validate_language(self, language: str | None) -> None:
        """Language validation helper — usable directly by every provider. None = auto-detect."""
        supported = self.supported_languages
        if language is None or supported == ["*"]:
            return
        if language not in supported:
            raise UnsupportedLanguageError(language, self.provider_name, supported)

    def validate_format(self, fmt: str) -> None:
        """Format validation helper — usable directly by every provider."""
        if fmt not in self.supported_formats:
            raise UnsupportedFormatError(fmt, self.provider_name, self.supported_formats)


class BaseTTS(ABC):
    """
    The required contract for every TTS provider.

    Every provider that inherits this class MUST implement every
    abstract method/property below. Otherwise Python raises
    TypeError when the provider is instantiated.

    How to add a new provider:
        1. Create a new file in providers/
        2. Inherit BaseTTS
        3. Implement every method below
        4. Add a branch in app/tools/factory.py
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Unique provider identifier.
        Example: 'openai', 'google', 'elevenlabs'
        """
        ...

    @property
    @abstractmethod
    def supported_voices(self) -> list[str]:
        """
        Voice names that can be used.
        Example: ['alloy', 'echo', 'nova']
        """
        ...

    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """
        Supported output audio formats.
        Example: ['mp3', 'wav', 'opus']
        """
        ...

    @abstractmethod
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        """
        Convert text to audio bytes.

        Args:
            request: TTSRequest with text, voice, format, speed

        Returns:
            TTSResult with audio_bytes, format, character_count, provider

        Raises:
            TTSError: if synthesis fails
            UnsupportedFormatError: if the format is not supported
        """
        ...

    def validate_format(self, fmt: str) -> None:
        """Format validation helper — usable directly by every provider."""
        if fmt not in self.supported_formats:
            raise UnsupportedFormatError(fmt, self.provider_name, self.supported_formats)

    def validate_voice(self, voice: str) -> None:
        """Voice validation helper — usable directly by every provider."""
        if voice not in self.supported_voices:
            raise ValueError(
                f"Voice '{voice}' is not supported by {self.provider_name}. "
                f"Available: {', '.join(self.supported_voices)}"
            )
