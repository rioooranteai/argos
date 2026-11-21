import logging

from app.services.voice.base.tts_base import BaseTTSProvider
from app.services.voice.exceptions import UnsupportedProviderError
from app.services.voice.providers.openai_tts import OpenAITTSProvider

logger = logging.getLogger(__name__)


class TTSFactory:
    """
    Factory that creates TTS provider instances.

    Providers available by default:
        - 'openai' : OpenAI TTS API (tts-1 / tts-1-hd)

    How to add a new provider without changing other code:
        TTSFactory.register("elevenlabs", ElevenLabsTTSProvider)
    """

    _providers: dict[str, type[BaseTTSProvider]] = {}

    @classmethod
    def _load_defaults(cls) -> None:
        """Register the built-in providers — lazy import so nothing fails when a library is not installed."""
        if not cls._providers:
            cls._providers["openai"] = OpenAITTSProvider

    @classmethod
    def create(cls, provider: str = "openai", **kwargs) -> BaseTTSProvider:
        """
        Create a TTS provider instance.

        Args:
            provider : Provider name ('openai', etc.)
            **kwargs : Extra arguments for the provider constructor

        Returns:
            Instance BaseTTSProvider

        Raises:
            UnsupportedProviderError: if the provider is not registered
        """
        cls._load_defaults()
        if provider not in cls._providers:
            raise UnsupportedProviderError(provider, list(cls._providers.keys()))

        logger.debug(f"[TTSFactory] Creating provider: {provider}")
        return cls._providers[provider](**kwargs)

    @classmethod
    def register(cls, name: str, provider_class: type[BaseTTSProvider]) -> None:
        """
        Register a new provider.

        Args:
            name           : Provider identifier (e.g. 'elevenlabs')
            provider_class : A class that inherits BaseTTSProvider
        """
        if not issubclass(provider_class, BaseTTSProvider):
            raise TypeError(f"{provider_class.__name__} must inherit from BaseTTSProvider")
        cls._providers[name] = provider_class
        logger.info(f"[TTSFactory] Provider '{name}' registered.")

    @classmethod
    def available_providers(cls) -> list[str]:
        cls._load_defaults()
        return list(cls._providers.keys())
