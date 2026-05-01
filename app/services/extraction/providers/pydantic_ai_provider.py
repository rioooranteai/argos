import logging
from pathlib import Path

from app.core.config import config
from app.services.extraction.base.extraction_base import BaseExtractionProvider
from app.services.extraction.exceptions import ExtractionAgentError
from app.services.extraction.model import CompetitorFeature
from pydantic_ai import Agent

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

    def __init__(self, model: str | None = None):
        resolved_model = model or config.OPENAI_LLM_MODEL
        system_prompt = _load_prompt(_PROMPT_PATH)

        self._agent = Agent(
            model=f"openai:{resolved_model}",
            output_type=list[CompetitorFeature],
            system_prompt=system_prompt,
        )

        logger.info(f"PydanticAIExtractionProvider siap dengan model: '{resolved_model}'")

    async def extract(self, text: str) -> list[CompetitorFeature]:
        try:
            result = await self._agent.run(text)
            return result.output
        except Exception as e:
            raise ExtractionAgentError(f"Agent gagal melakukan ekstraksi: {e}") from e
