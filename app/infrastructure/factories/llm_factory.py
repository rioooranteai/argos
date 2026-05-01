from app.core.config import config
from app.infrastructure.interface.llm import BaseLLM

from app.infrastructure.providers.llms.openai_llm import OpenAILLM

def get_llm(model_type: str = "llm", temperature: float = 0.0) -> BaseLLM:
    provider = config.LLM_PROVIDER.lower()

    if provider == "openai":
        if model_type == "llm":
            selected_model = config.OPENAI_LLM_MODEL
        elif model_type == "title":
            selected_model = config.OPENAI_TITLE_MODEL
        else:
            selected_model = config.OPENAI_EXTRACTION_MODEL

        return OpenAILLM(
            api_key=config.OPENAI_API_KEY,
            model=selected_model,
            temperature=temperature
        )

    raise ValueError(f"LLMFactory — unknown provider: '{provider}'")
