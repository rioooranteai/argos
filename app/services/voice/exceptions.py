class VoiceServiceError(Exception):
    """Base exception untuk semua voice service error."""


class TTSError(VoiceServiceError):
    """Error saat proses Text-to-Speech."""


class STTError(VoiceServiceError):
    """Error saat proses Speech-to-Text."""


class UnsupportedProviderError(VoiceServiceError):
    """Provider tidak terdaftar di factory."""

    def __init__(self, provider: str, available: list[str]):
        self.provider = provider
        self.available = available
        super().__init__(
            f"Provider '{provider}' tidak didukung. "
            f"Tersedia: {', '.join(available)}"
        )


class UnsupportedFormatError(VoiceServiceError):
    """Format audio tidak didukung provider."""

    def __init__(self, fmt: str, provider: str, supported: list[str]):
        super().__init__(
            f"Format '{fmt}' tidak didukung oleh {provider}. "
            f"Format yang didukung: {', '.join(supported)}"
        )


class UnsupportedLanguageError(VoiceServiceError):
    """Bahasa tidak didukung provider."""

    def __init__(self, language: str, provider: str, supported: list[str]):
        super().__init__(
            f"Bahasa '{language}' tidak didukung oleh {provider}. "
            f"Bahasa yang didukung: {', '.join(supported)}"
        )


class ProviderUnavailableError(VoiceServiceError):
    """Provider tidak bisa diakses / health check gagal."""

    def __init__(self, provider: str, reason: str = ""):
        super().__init__(
            f"Provider '{provider}' tidak tersedia. {reason}".strip()
        )
