import logging
from typing import Type, Any
from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from app.services.shared.base.llm import BaseLLM

logger = logging.getLogger(__name__)

class OpenAILLM(BaseLLM):
    """Implementasi konkrit untuk provider OpenAI."""
    
    def __init__(self, api_key: str, model: str, temperature: float = 0.0):
        logger.info(f"Membangun mesin OpenAILLM (Model: {model}, Temp: {temperature})")
        # Inisialisasi Langchain ChatOpenAI di sini
        self._client = ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature
        )

    def invoke(self, prompt: str, system: str | None = None) -> str:
        # Implementasi standar
        pass

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        # Implementasi standar
        pass

    def with_structured_output(self, schema: Type[BaseModel]) -> "BaseLLM":
        # Implementasi untuk extraction agent
        pass

    def get_client(self) -> Any:
        """Mengekspos objek ChatOpenAI ke luar untuk dirakit dengan LCEL."""
        return self._client