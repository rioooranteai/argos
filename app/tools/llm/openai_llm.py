import logging

from langchain_openai import ChatOpenAI

from app.core.config import app_config
from app.core.observability.ai_calls.recorder import recorder, usage_from_langchain
from app.tools.llm.base import BaseLLM

logger = logging.getLogger(__name__)


def _sampling(temperature: float, reasoning_effort: str | None) -> dict:
    """Reasoning models (gpt-6-luna) take ``reasoning_effort`` and reject a custom
    ``temperature`` (only the default is accepted), so it is sent for one or the other."""
    if reasoning_effort:
        return {"reasoning_effort": reasoning_effort}
    return {"temperature": temperature}


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
        reasoning_effort: str | None = None,
    ):
        logger.info(
            "Building OpenAILLM (purpose: %s, model: %s, temp: %s, reasoning: %s, timeout: %ss, retries: %s)",
            purpose, model, "default" if reasoning_effort else temperature, reasoning_effort,
            timeout, max_retries,
        )
        self._model = model
        self._purpose = purpose  # the `purpose` column in llm_calls
        # Explicit timeout & retries (SDK default: 600 s). SDK retries only cover
        # recoverable errors: connection, timeout, 408/409/429/5xx.
        self._client = ChatOpenAI(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            **_sampling(temperature, reasoning_effort),
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
            call.content(input=messages, output=response.content)
        self._log_response(response.content)
        return response.content

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        messages = self._build_messages(prompt, system)
        self._log_prompt(messages)
        with recorder.track(self._purpose, self._model) as call:
            response = await self._client.ainvoke(messages)
            call.usage(*usage_from_langchain(response))
            call.content(input=messages, output=response.content)
        self._log_response(response.content)
        return response.content

    # Prompts can contain confidential document content: only logged when LOG_PROMPTS = True.
    def _log_prompt(self, messages: list) -> None:
        if app_config.LOG_PROMPTS:
            logger.debug("[%s] prompt: %s", self._purpose, messages)

    def _log_response(self, content: object) -> None:
        if app_config.LOG_PROMPTS:
            logger.debug("[%s] respons: %s", self._purpose, content)

