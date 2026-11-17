from app.core.config import config
from app.infrastructure.interface.llm import BaseLLM

from app.infrastructure.providers.llms.openai_llm import OpenAILLM

def get_llm(model_type: str = "llm", temperature: float = 0.0) -> BaseLLM:
    provider = config.LLM_PROVIDER.lower()

    if provider == "openai":
        models = {
            "llm": config.OPENAI_LLM_MODEL,
            "chat": config.OPENAI_CHAT_MODEL,
            "router": config.OPENAI_ROUTER_MODEL,
            "title": config.OPENAI_TITLE_MODEL,
            "extraction": config.OPENAI_EXTRACTION_MODEL,
        }
        if model_type not in models:
            raise ValueError(f"LLMFactory — unknown model_type: '{model_type}'")
        selected_model = models[model_type]

        return OpenAILLM(
            api_key=config.OPENAI_API_KEY,
            model=selected_model,
            temperature=temperature
        )

    raise ValueError(f"LLMFactory — unknown provider: '{provider}'")
