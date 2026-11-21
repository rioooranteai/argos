import logging

from app.services.voice.base.stt_base import BaseSTTProvider
from app.services.voice.exceptions import UnsupportedProviderError
from app.services.voice.providers.openai_stt import OpenAISTTProvider

logger = logging.getLogger(__name__)


class STTFactory:
    """
    Factory that creates STT provider instances.

    Available providers:
        - 'openai_whisper' : Whisper via OpenAI API (default)

    How to add a new provider:
        STTFactory.register("deepgram", DeepgramSTTProvider)
    """

    _providers: dict[str, type[BaseSTTProvider]] = {
        "openai_whisper": OpenAISTTProvider,
    }

    @classmethod
    def create(cls, provider: str = "openai_whisper", **kwargs) -> BaseSTTProvider:
        """
        Create an STT provider instance.

        Args:
            provider : Provider name (default: 'openai_whisper')
            **kwargs : Extra arguments for the provider constructor
                       Example: model='whisper-1', language='id'

        Returns:
            Instance BaseSTTProvider

        Raises:
            UnsupportedProviderError: if the provider is not registered
        """
        if provider not in cls._providers:
            raise UnsupportedProviderError(provider, list(cls._providers.keys()))

        logger.debug(f"[STTFactory] Creating provider: {provider}")
        return cls._providers[provider](**kwargs)

    @classmethod
    def register(cls, name: str, provider_class: type[BaseSTTProvider]) -> None:
        """
        Register a new provider.

        Args:
            name           : Provider identifier (e.g. 'deepgram')
            provider_class : A class that inherits BaseSTTProvider
        """
        if not issubclass(provider_class, BaseSTTProvider):
            raise TypeError(f"{provider_class.__name__} must inherit from BaseSTTProvider")
        cls._providers[name] = provider_class
        logger.info(f"[STTFactory] Provider '{name}' registered.")

    @classmethod
    def available_providers(cls) -> list[str]:
        return list(cls._providers.keys())