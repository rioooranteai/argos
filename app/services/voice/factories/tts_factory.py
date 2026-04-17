import logging

from app.services.voice.base.tts_base import BaseTTSProvider
from app.services.voice.exceptions import UnsupportedProviderError
from app.services.voice.providers.openai_tts import OpenAITTSProvider

logger = logging.getLogger(__name__)


class TTSFactory:
    """
    Factory untuk membuat instance TTS provider.

    Provider yang tersedia secara default:
        - 'openai' : OpenAI TTS API (tts-1 / tts-1-hd)

    Cara tambah provider baru tanpa ubah kode lain:
        TTSFactory.register("elevenlabs", ElevenLabsTTSProvider)
    """

    _providers: dict[str, type[BaseTTSProvider]] = {}

    @classmethod
    def _load_defaults(cls) -> None:
        """Register provider bawaan — lazy import supaya tidak error kalau lib belum install."""
        if not cls._providers:
            cls._providers["openai"] = OpenAITTSProvider

    @classmethod
    def create(cls, provider: str = "openai", **kwargs) -> BaseTTSProvider:
        """
        Buat instance provider TTS.

        Args:
            provider : Nama provider ('openai', dst.)
            **kwargs : Argumen tambahan untuk constructor provider

        Returns:
            Instance BaseTTSProvider

        Raises:
            UnsupportedProviderError: jika provider tidak terdaftar
        """
        cls._load_defaults()
        if provider not in cls._providers:
            raise UnsupportedProviderError(provider, list(cls._providers.keys()))

        logger.debug(f"[TTSFactory] Creating provider: {provider}")
        return cls._providers[provider](**kwargs)

    @classmethod
    def register(cls, name: str, provider_class: type[BaseTTSProvider]) -> None:
        """
        Daftarkan provider baru.

        Args:
            name           : Identifier provider (misal: 'elevenlabs')
            provider_class : Class yang inherit BaseTTSProvider
        """
        if not issubclass(provider_class, BaseTTSProvider):
            raise TypeError(f"{provider_class.__name__} harus inherit dari BaseTTSProvider")
        cls._providers[name] = provider_class
        logger.info(f"[TTSFactory] Provider '{name}' berhasil didaftarkan.")

    @classmethod
    def available_providers(cls) -> list[str]:
        cls._load_defaults()
        return list(cls._providers.keys())
