class VoiceServiceError(Exception):
    """Base exception for every voice service error."""


class TTSError(VoiceServiceError):
    """Error during Text-to-Speech."""


class STTError(VoiceServiceError):
    """Error during Speech-to-Text."""


class UnsupportedProviderError(VoiceServiceError):
    """The provider is not registered in the factory."""

    def __init__(self, provider: str, available: list[str]):
        self.provider = provider
        self.available = available
        super().__init__(
            f"Provider '{provider}' is not supported. "
            f"Available: {', '.join(available)}"
        )


class UnsupportedFormatError(VoiceServiceError):
    """The audio format is not supported by the provider."""

    def __init__(self, fmt: str, provider: str, supported: list[str]):
        super().__init__(
            f"Format '{fmt}' is not supported by {provider}. "
            f"Supported formats: {', '.join(supported)}"
        )


class UnsupportedLanguageError(VoiceServiceError):
    """The language is not supported by the provider."""

    def __init__(self, language: str, provider: str, supported: list[str]):
        super().__init__(
            f"Language '{language}' is not supported by {provider}. "
            f"Supported languages: {', '.join(supported)}"
        )


class ProviderUnavailableError(VoiceServiceError):
    """The provider cannot be reached / its health check failed."""

    def __init__(self, provider: str, reason: str = ""):
        super().__init__(
            f"Provider '{provider}' is unavailable. {reason}".strip()
        )
