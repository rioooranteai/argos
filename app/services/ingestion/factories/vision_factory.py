import logging
from pathlib import Path
from app.services.ingestion.base.vision import BaseVisionProcessor
from app.services.ingestion.providers.vision.openai_vision import OpenAIVisionProcessor

logger = logging.getLogger(__name__)

class VisionFactory:
    """
    Factory that picks and assembles the Vision Processor.
    It loads the heavy configuration (such as the prompt file) up front.
    """

    def __init__(self):
        prompt_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "prompts" / "vision_description.md"

        self._vision_prompt = self._load_prompt(prompt_path)

    def _load_prompt(self, path: Path) -> str:
        """Read the markdown file safely."""
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return (
                "You are an expert data analyst. "
                "Describe this chart or image in detail."
            )

    def get_processor(self) -> BaseVisionProcessor:
        """
        Assemble and return an OpenAIVisionProcessor instance
        with the loaded prompt injected.
        """
        return OpenAIVisionProcessor(prompt_template=self._vision_prompt)