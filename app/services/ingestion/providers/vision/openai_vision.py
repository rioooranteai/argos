import base64
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import Config
from app.services.ingestion.base.vision import BaseVisionProcessor
from app.services.ingestion.models import DocumentElement, ElementType
from app.services.ingestion.exceptions import VisionProcessingError

logger = logging.getLogger(__name__)

class OpenAIVisionProcessor(BaseVisionProcessor):
    """
    Memproses ekstraksi visual dari gambar ke teks menggunakan model OpenAI Vision
    secara asynchronous agar tidak memblokir pipeline utama.
    """

    def __init__(self, prompt_template: str): # <--- Menerima prompt dari Factory
        self.prompt_template = prompt_template
        try:
            self.vision_model = ChatOpenAI(
                model=Config.OPENAI_VLM_MODEL,
                api_key=Config.OPENAI_API_KEY,
                temperature=0.0,
                max_tokens=1500,
                timeout=45,
                max_retries=2,
            )
        except Exception as e:
            raise

    def supports(self, element: DocumentElement) -> bool:
        """Hanya memproses elemen berjenis FIGURE yang memiliki byte gambar."""
        return (
            element.element_type == ElementType.FIGURE
            and element.image_bytes is not None
        )

    async def describe_image(self, element: DocumentElement) -> str:
        """
        Kirim gambar ke OpenAI dan eksekusi secara async.
        """
        if not self.supports(element):
            return ""

        try:
            base64_image = base64.b64encode(element.image_bytes).decode("utf-8")

            context_note = ""
            if element.section_heading:
                context_note = (
                    f"\n\nDocument Context: "
                    f"This image is located under the section titled '{element.section_heading}'."
                )

            system_instruction = self.prompt_template + context_note

            message = HumanMessage(
                content=[
                    {"type": "text", "text": system_instruction},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ]
            )


            response = await self.vision_model.ainvoke([message])

            return response.content.strip()

        except Exception as e:
            raise VisionProcessingError(
                page_number=element.page_number,
                reason=str(e)
            )