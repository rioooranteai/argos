"""Document parser contract: parsed elements, errors, ``BaseDocumentLoader``, ``BaseDocumentParser``.

Two levels:
- ``BaseDocumentLoader`` — synchronous, reads one file (e.g. Docling). Runs inside the
  parser subprocess.
- ``BaseDocumentParser`` — what the pipeline uses: async, with a time limit, so a
  hanging loader can be stopped.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ElementType(str, Enum):
    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    LIST_ITEM = "list_item"
    FIGURE = "figure"
    CAPTION = "caption"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"


class DocumentElement(BaseModel):
    """One parsed element (text/table/image), in document order."""

    element_type: ElementType
    content: str
    page_number: int = 0
    section_heading: str = ""
    image_bytes: bytes | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentParserError(Exception):
    """Base exception for every document parser error."""


class DocumentLoadError(DocumentParserError):
    """Failed to parse or read the document."""

    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Failed to load document '{file_path}': {reason}")


class ParserUnavailable(DocumentParserError):
    """The parser died, failed to start, or was stopped after a timeout.
    Temporary: the job may be retried."""


class ParserTimeout(ParserUnavailable):
    """Parsing went over the time limit; the parser was stopped."""


class BaseDocumentLoader(ABC):
    """Reads one file into elements (synchronous)."""

    @abstractmethod
    def supports(self, file_path: str) -> bool:
        """
        Return True if this loader can handle the file.
        Usually checked from the extension or MIME type.
        """

    @abstractmethod
    def load(self, file_path: str) -> list[DocumentElement]:
        """
        Parse the document and return a list of structured elements.
        The elements must be in the order they appear in the document.

        Raises:
            DocumentLoadError: if the document cannot be read.
        """


class BaseDocumentParser(ABC):
    """What the pipeline calls: async parsing with a time limit."""

    @abstractmethod
    async def parse(self, path: str, timeout: float) -> list[DocumentElement]:
        """
        Raises:
            DocumentLoadError: the document cannot be read (permanent).
            ParserUnavailable / ParserTimeout: the parser failed (temporary).
        """

    def a4_page_equivalents(self, path: str) -> float | None:
        """How much page surface the document has, in A4 pages (a newspaper-sized page counts as
        several). Used to size the parse time limit. None = unknown (the page count is used)."""
        return None

    async def start(self) -> None:
        """Prepare the parser (e.g. load models). Optional."""

    async def stop(self) -> None:
        """Release resources. Optional."""

    @property
    def is_alive(self) -> bool:
        """For /health/ready: whether the parser is running right now."""
        return True
