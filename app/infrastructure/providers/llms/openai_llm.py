import logging
from typing import Type

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import app_config
from app.infrastructure.interface.llm import BaseLLM
from app.core.observability.recorder import recorder, usage_from_langchain

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """Concrete implementation for the OpenAI provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        timeout: float = 60,
        max_retries: int = 1,
        purpose: str = "synthesizer",
    ):
        logger.info(
            "Building OpenAILLM (purpose: %s, model: %s, temp: %s, timeout: %ss, retries: %s)",
            purpose, model, temperature, timeout, max_retries,
        )
        self._model = model
        self._purpose = purpose  # the `purpose` column in llm_calls
        # Explicit timeout & retries (SDK default: 600 s). SDK retries only cover
        # recoverable errors: connection, timeout, 408/409/429/5xx.
        self._client = ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _build_messages(self, prompt: str, system: str | None) -> list:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def invoke(self, prompt: str, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        self._log_prompt(messages)
        with recorder.track(self._purpose, self._model) as call:
            response = self._client.invoke(messages)
            call.usage(*usage_from_langchain(response))
        self._log_response(response.content)
        return response.content

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        self._log_prompt(messages)
        with recorder.track(self._purpose, self._model) as call:
            response = await self._client.ainvoke(messages)
            call.usage(*usage_from_langchain(response))
        self._log_response(response.content)
        return response.content

    # Prompts can contain confidential document content: only logged when LOG_PROMPTS = True
    # (DESIGN_GROUP_C.md §7.5).
    def _log_prompt(self, messages: list) -> None:
        if app_config.LOG_PROMPTS:
            logger.debug("[%s] prompt: %s", self._purpose, messages)

    def _log_response(self, content: object) -> None:
        if app_config.LOG_PROMPTS:
            logger.debug("[%s] respons: %s", self._purpose, content)

    def with_structured_output(self, schema: Type[BaseModel]) -> "BaseLLM":
        raise NotImplementedError("with_structured_output is not implemented yet")
