import logging
from pathlib import Path
from app.services.ingestion.base.vision import BaseVisionProcessor
from app.services.ingestion.providers.vision.openai_vision import OpenAIVisionProcessor

logger = logging.getLogger(__name__)

class VisionFactory:
    """
    Factory pattern untuk memilih dan merakit Vision Processor.
    Bertugas memuat konfigurasi berat (seperti file prompt) di awal.
    """

    def __init__(self):
        prompt_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "prompts" / "vision_description.md"

        self._vision_prompt = self._load_prompt(prompt_path)

    def _load_prompt(self, path: Path) -> str:
        """Membaca isi file markdown dengan aman."""
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return (
                "Kamu adalah ahli analis data. "
                "Tolong deskripsikan grafik atau gambar ini secara detail."
            )

    def get_processor(self) -> BaseVisionProcessor:
        """
        Merakit dan mengembalikan instance OpenAIVisionProcessor
        dengan menyuntikkan prompt yang sudah diload.
        """
        return OpenAIVisionProcessor(prompt_template=self._vision_prompt)