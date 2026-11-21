from __future__ import annotations


class IngestionError(Exception):
    """Base exception for every error in the ingestion layer."""


class DocumentLoadError(IngestionError):
    """Failed to parse or read the document."""

    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Failed to load document '{file_path}': {reason}")


class UnsupportedFileTypeError(IngestionError):
    """No provider supports this file type."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        super().__init__(f"Unsupported file type: '{file_path}'")


class ChunkingError(IngestionError):
    """Failed to chunk a document element."""

    def __init__(self, element_type: str, reason: str):
        self.element_type = element_type
        super().__init__(f"Failed to chunk element '{element_type}': {reason}")


class DuplicateDocumentError(IngestionError):
    """The document was already ingested (idempotency check)."""

    def __init__(self, file_path: str, doc_hash: str):
        self.file_path = file_path
        self.doc_hash = doc_hash
        super().__init__(
            f"Document already exists (hash: {doc_hash}): '{file_path}'"
        )


class VisionProcessingError(IngestionError):
    """Failed to process an image via the VLM."""

    def __init__(self, page_number: int, reason: str):
        self.page_number = page_number
        super().__init__(
            f"Failed to process the figure on page {page_number}: {reason}"
        )