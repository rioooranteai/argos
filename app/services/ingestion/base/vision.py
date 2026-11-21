from __future__ import annotations
from abc import ABC, abstractmethod
from app.services.ingestion.model import DocumentElement

class BaseVisionProcessor(ABC):
    """
    Model Contract :
        - chunk
    """

    @abstractmethod
    def supports(self, element: DocumentElement) -> bool:
        """
        Return True if this element can be processed.
        Usually only True for an ElementType.FIGURE that has image_bytes.
        """

    @abstractmethod
    async def describe_image(self, element: DocumentElement) -> str:
        """
        Send the image to the VLM and return a text description.
        The description must cover: numbers, labels, trends and visual context.

        Raises:
            VisionProcessingError: if the VLM fails to process the image.
        """