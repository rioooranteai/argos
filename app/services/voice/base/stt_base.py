from abc import ABC, abstractmethod

from app.services.voice.exceptions import UnsupportedFormatError
from app.services.voice.exceptions import UnsupportedLanguageError
from app.services.voice.model import STTRequest, STTResult


class BaseSTTProvider(ABC):
    """
    The required contract for every STT provider.

    Every provider that inherits this class MUST implement every
    abstract method/property below. Otherwise Python raises
    TypeError when the provider is instantiated.

    How to add a new provider:
        1. Create a new file in providers/
        2. Inherit BaseSTTProvider
        3. Implement every method below
        4. Register it in STTFactory
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
