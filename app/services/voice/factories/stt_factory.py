import logging

from app.services.voice.base.stt_base import BaseSTTProvider
from app.services.voice.exceptions import UnsupportedProviderError
from app.services.voice.providers.openai_stt import OpenAISTTProvider

logger = logging.getLogger(__name__)


class STTFactory:
    """
    Factory untuk membuat instance STT provider.

    Provider yang tersedia:
        - 'openai_whisper' : Whisper via OpenAI API (default)

    Cara tambah provider baru:
        STTFactory.register("deepgram", DeepgramSTTProvider)
    """

    _providers: dict[str, type[BaseSTTProvider]] = {
        "openai_whisper": OpenAISTTProvider,
    }

    @classmethod
    def create(cls, provider: str = "openai_whisper", **kwargs) -> BaseSTTProvider:
        """
        Buat instance provider STT.

        Args:
            provider : Nama provider (default: 'openai_whisper')
            **kwargs : Argumen tambahan untuk constructor provider
                       Contoh: model='whisper-1', language='id'

        Returns:
            Instance BaseSTTProvider

        Raises:
            UnsupportedProviderError: jika provider tidak terdaftar
        """
        if provider not in cls._providers:
            raise UnsupportedProviderError(provider, list(cls._providers.keys()))

        logger.debug(f"[STTFactory] Creating provider: {provider}")
        return cls._providers[provider](**kwargs)

    @classmethod
    def register(cls, name: str, provider_class: type[BaseSTTProvider]) -> None:
        """
        Daftarkan provider baru.

        Args:
            name           : Identifier provider (misal: 'deepgram')
            provider_class : Class yang inherit BaseSTTProvider
        """
        if not issubclass(provider_class, BaseSTTProvider):
            raise TypeError(f"{provider_class.__name__} harus inherit dari BaseSTTProvider")
        cls._providers[name] = provider_class
        logger.info(f"[STTFactory] Provider '{name}' berhasil didaftarkan.")

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._providers.keys())