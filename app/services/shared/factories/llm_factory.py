from __future__ import annotations

import logging

from app.core.config import Config
from app.services.shared.base.llm import BaseLLM

logger = logging.getLogger(__name__)


def get_llm() -> BaseLLM:
    """Instantiate and return the active LLM based on config.

    Reads ``LLM_PROVIDER`` from :class:`~app.core.config.Config` and
    returns the corresponding :class:`~app.services.shared.base.llm.BaseLLM`
    implementation.

    Available providers:
        - ``openai``: OpenAI chat completion model (default: gpt-4o-mini).

    Returns:
        A concrete ``BaseLLM`` instance ready for use.

    Raises:
        ValueError: If ``LLM_PROVIDER`` refers to an unsupported provider.
    """
    provider = Config.LLM_PROVIDER.lower()

    if provider == "openai":
        from app.services.shared.providers.llms.openai_llm import OpenAILLM
        logger.info(
            "LLMFactory — provider: OpenAI, model: %s",
            Config.OPENAI_LLM_MODEL,
        )
        return OpenAILLM(
            api_key=Config.OPENAI_API_KEY,
            model=Config.OPENAI_LLM_MODEL,
        )

    raise ValueError(
        f"LLMFactory — unknown provider: '{provider}'. "
        f"Supported: ['openai']"
    )