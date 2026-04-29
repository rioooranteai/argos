import logging
from typing import Type

from app.infrastructure.interface.llm import BaseLLM
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """Implementasi konkrit untuk provider OpenAI."""

    def __init__(self, api_key: str, model: str, temperature: float = 0.0):
        logger.info(f"Membangun mesin OpenAILLM (Model: {model}, Temp: {temperature})")
        self._client = ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature
        )

    def _build_messages(self, prompt: str, system: str | None) -> list:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def invoke(self, prompt: str, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        response = self._client.invoke(messages)
        return response.content

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        response = await self._client.ainvoke(messages)
        return response.content

    def with_structured_output(self, schema: Type[BaseModel]) -> "BaseLLM":
        raise NotImplementedError("with_structured_output belum diimplementasi")
