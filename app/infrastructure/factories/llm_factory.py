from app.core.config import app_config, secrets
from app.infrastructure.interface.llm import BaseLLM
from app.infrastructure.providers.llms.openai_llm import OpenAILLM

# model_type → (model, timeout detik, retry). DESIGN_GROUP_B.md §5.
_OPENAI_PROFILES = {
    "llm": (app_config.OPENAI_LLM_MODEL, app_config.LLM_TIMEOUT_CHAT, 1),
    "chat": (app_config.OPENAI_CHAT_MODEL, app_config.LLM_TIMEOUT_CHAT, 1),
    "router": (app_config.OPENAI_ROUTER_MODEL, app_config.LLM_TIMEOUT_ROUTER, 1),
    "title": (app_config.OPENAI_TITLE_MODEL, app_config.LLM_TIMEOUT_TITLE, 0),
    "nl2sql": (app_config.OPENAI_EXTRACTION_MODEL, app_config.LLM_TIMEOUT_NL2SQL, 1),
}


def get_llm(model_type: str = "llm", temperature: float = 0.0) -> BaseLLM:
    provider = app_config.LLM_PROVIDER.lower()

    if provider == "openai":
        if model_type not in _OPENAI_PROFILES:
            raise ValueError(f"LLMFactory — unknown model_type: '{model_type}'")
        model, timeout, retries = _OPENAI_PROFILES[model_type]
        return OpenAILLM(
            api_key=secrets.OPENAI_API_KEY,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_retries=retries,
        )

    raise ValueError(f"LLMFactory — unknown provider: '{provider}'")
