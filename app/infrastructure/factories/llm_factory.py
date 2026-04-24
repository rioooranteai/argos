from app.core.config import config
from app.core.interface.llm import BaseLLM

from app.infrastructure.providers.llms.openai_llm import OpenAILLM


def get_llm(model_type: str = "llm", temperature: float = 0.0) -> BaseLLM:
    provider = config.LLM_PROVIDER.lower()

    if provider == "openai":
        selected_model = config.OPENAI_LLM_MODEL if model_type == "llm" else config.OPENAI_EXTRACTION_MODEL

        return OpenAILLM(
            api_key=config.OPENAI_API_KEY,
            model=selected_model,
            temperature=temperature
        )

    raise ValueError(f"LLMFactory — unknown provider: '{provider}'")
