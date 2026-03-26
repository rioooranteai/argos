from __future__ import annotations


class IngestionError(Exception):
    """Base exception untuk semua error di ingestion layer."""


class DocumentLoadError(IngestionError):
    """Gagal mem-parse atau membaca dokumen."""

    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Gagal memuat dokumen '{file_path}': {reason}")


class UnsupportedFileTypeError(IngestionError):
    """Tipe file tidak didukung oleh provider manapun."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        super().__init__(f"Tipe file tidak didukung: '{file_path}'")


class ChunkingError(IngestionError):
    """Gagal melakukan chunking pada elemen dokumen."""

    def __init__(self, element_type: str, reason: str):
        self.element_type = element_type
        super().__init__(f"Gagal chunk elemen '{element_type}': {reason}")


class DuplicateDocumentError(IngestionError):
    """Dokumen sudah pernah di-ingest sebelumnya (idempotency check)."""

    def __init__(self, file_path: str, doc_hash: str):
        self.file_path = file_path
        self.doc_hash = doc_hash
        super().__init__(
            f"Dokumen sudah ada (hash: {doc_hash}): '{file_path}'"
        )


class VisionProcessingError(IngestionError):
    """Gagal memproses gambar via VLM."""

    def __init__(self, page_number: int, reason: str):
        self.page_number = page_number
        super().__init__(
            f"Gagal proses figure halaman {page_number}: {reason}"
        )