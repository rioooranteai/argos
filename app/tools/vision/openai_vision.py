import base64
import logging

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import app_config, secrets
from app.core.observability.recorder import recorder, usage_from_langchain
from app.tools.document_parser.base import DocumentElement, ElementType
from app.tools.vision.base import BaseVisionModel, VisionProcessingError

logger = logging.getLogger(__name__)

class OpenAIVision(BaseVisionModel):
    """
    Turns images into text with an OpenAI Vision model,
    asynchronously so the main pipeline is not blocked.
    """

    def __init__(self, prompt_template: str, reasoning_effort: str | None = None):
        self.prompt_template = prompt_template  # loaded by tools/factory.py
        # A reasoning model takes reasoning_effort and only the default temperature.
        sampling = {"reasoning_effort": reasoning_effort} if reasoning_effort else {"temperature": 0.0}
        self.vision_model = ChatOpenAI(
            model=app_config.OPENAI_VLM_MODEL,
            api_key=secrets.OPENAI_API_KEY,
            max_tokens=1500,
            timeout=app_config.VISION_TIMEOUT,
            max_retries=2,
            **sampling,
        )

    def supports(self, element: DocumentElement) -> bool:
        """Only processes FIGURE elements that have image bytes."""
        return (
            element.element_type == ElementType.FIGURE
            and element.image_bytes is not None
        )

    async def describe_image(self, element: DocumentElement) -> str:
        """
        Send the image to OpenAI and run it asynchronously.
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


            with recorder.track("vision", app_config.OPENAI_VLM_MODEL) as call:
                response = await self.vision_model.ainvoke([message])
                call.usage(*usage_from_langchain(response))
                # The image itself is never sent to the trace, only its size and the prompt.
                call.content(
                    input={"prompt": system_instruction, "page": element.page_number,
                           "image_bytes": len(element.image_bytes)},
                    output=response.content,
                )

            return response.content.strip()

        except Exception as e:
            raise VisionProcessingError(
                page_number=element.page_number,
                reason=str(e)
            ) from e
