from __future__ import annotations

import logging
from typing import Type

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import Config
from app.services.shared.base.llm import BaseLLM

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """
    LLM provider menggunakan LangChain ChatOpenAI.
    Mendukung structured output via Pydantic schema.
    """

    def __init__(self):
        self._client = ChatOpenAI(
            api_key=Config.OPENAI_API_KEY,
            model=Config.OPENAI_LLM_MODEL,
            temperature=0.0,
        )
        self._schema = None

    def invoke(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        try:
            response = self._client.invoke(messages)
            return response.content
        except Exception as e:
            logger.error("LLM invoke gagal: %s", e)
            raise

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        try:
            response = await self._client.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("LLM ainvoke gagal: %s", e)
            raise

    def with_structured_output(self, schema: Type[BaseModel]) -> "OpenAILLM":
        """
        Return instance baru dengan structured output aktif.
        Instance asli tidak dimodifikasi.
        """
        new_instance = OpenAILLM()
        new_instance._schema = schema
        new_instance._client = self._client.with_structured_output(schema)
        return new_instance