import logging
from pathlib import Path

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import app_config, secrets
from app.services.extraction.base.extraction_base import BaseExtractionProvider
from app.services.extraction.exceptions import ExtractionAgentError
from app.services.extraction.model import ExtractedFeature

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "extraction_agent.md"


def _load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Extraction prompt not found at: {path}. "
            "Ensure 'prompts/extraction_agent.md' exists in the project root."
        )
    return path.read_text(encoding="utf-8")


class PydanticAIExtractionProvider(BaseExtractionProvider):
    def __init__(self, model: str | None = None, timeout: float | None = None, max_retries: int = 2):
        resolved_model = model or app_config.OPENAI_LLM_MODEL
        system_prompt = _load_prompt(_PROMPT_PATH)

        # Klien OpenAI eksplisit: API key dari Secrets (.env tidak dimuat ke env OS),
        # timeout & retry HTTP (timeout/429/5xx) diatur di sini, tidak memakai default 600 dtk.
        client = AsyncOpenAI(
            api_key=secrets.OPENAI_API_KEY,
            timeout=timeout or app_config.EXTRACTION_TIMEOUT,
            max_retries=max_retries,
        )
        self._agent = Agent(
            model=OpenAIChatModel(resolved_model, provider=OpenAIProvider(openai_client=client)),
            output_type=list[ExtractedFeature],
            system_prompt=system_prompt,
        )
        logger.info(f"PydanticAIExtractionProvider siap dengan model: '{resolved_model}'")

    async def extract(self, text: str) -> list[ExtractedFeature]:
        try:
            result = await self._agent.run(text)
            return result.output
        except Exception as e:
            raise ExtractionAgentError(f"Agent gagal melakukan ekstraksi: {e}") from e
