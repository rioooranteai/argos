"""Vision model contract: describes images found in documents."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.tools.document_parser.base import DocumentElement


class VisionProcessingError(Exception):
    """Failed to process an image via the vision model."""

    def __init__(self, page_number: int, reason: str):
        self.page_number = page_number
        super().__init__(f"Failed to process the figure on page {page_number}: {reason}")


class BaseVisionModel(ABC):
    @abstractmethod
    def supports(self, element: DocumentElement) -> bool:
        """
        Return True if this element can be processed.
        Usually only True for an ElementType.FIGURE that has image_bytes.
        """

    @abstractmethod
    async def describe_image(self, element: DocumentElement) -> str:
        """
        Send the image to the vision model and return a text description.
        The description must cover: numbers, labels, trends and visual context.

        Raises:
            VisionProcessingError: if the model fails to process the image.
        """
