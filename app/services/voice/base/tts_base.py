from abc import ABC, abstractmethod

from app.services.voice.exceptions import UnsupportedFormatError
from app.services.voice.model import TTSRequest, TTSResult


class BaseTTSProvider(ABC):
    """
    The required contract for every TTS provider.

    Every provider that inherits this class MUST implement every
    abstract method/property below. Otherwise Python raises
    TypeError when the provider is instantiated.

    How to add a new provider:
        1. Create a new file in providers/
        2. Inherit BaseTTSProvider
        3. Implement every method below
        4. Register it in TTSFactory
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
