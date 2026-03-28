import logging
from app.core.config import Config
from app.services.shared.base.llm import BaseLLM

logger = logging.getLogger(__name__)

def get_llm(model_type: str = "llm", temperature: float = 0.0) -> BaseLLM:
    provider = Config.LLM_PROVIDER.lower()

    if provider == "openai":
        # Import class provider kita secara dinamis
        from app.services.shared.providers.llms.openai_llm import OpenAILLM
        
        selected_model = Config.OPENAI_LLM_MODEL if model_type == "llm" else Config.OPENAI_EXTRACTION_MODEL
        
        return OpenAILLM(
            api_key=Config.OPENAI_API_KEY,
            model=selected_model,
            temperature=temperature
        )

    raise ValueError(f"LLMFactory — unknown provider: '{provider}'")