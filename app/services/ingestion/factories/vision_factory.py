import logging

from app.core.config import Config
from app.services.ingestion.base.vision import BaseVisionProcessor
from app.services.ingestion.providers.vision.openai_vision import OpenAIVisionProcessor

logger = logging.getLogger(__name__)


class VisionFactory:
    """
    Factory pattern untuk menyajikan model Vision (VLM)
    berdasarkan konfigurasi environment (.env).
    """

    @staticmethod
    def get_processor() -> BaseVisionProcessor:
        """
        Mengembalikan instance VisionProcessor sesuai Config.LLM_PROVIDER.
        """
        provider = Config.LLM_PROVIDER.lower()
        logger.info(f"Inisialisasi Vision Processor menggunakan provider: {provider}")

        if provider == "openai":
            return OpenAIVisionProcessor()
        # elif provider == "anthropic":
        #     return AnthropicVisionProcessor()
        else:
            logger.warning(
                f"Provider '{provider}' tidak didukung untuk Vision. "
                "Jatuh kembali (fallback) ke OpenAI."
            )
            return OpenAIVisionProcessor()
