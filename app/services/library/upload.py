"""Safe handling of uploaded files (DESIGN_GROUP_B.md §8).

- Files are read in chunks (1 MB) and stopped as soon as they go over the size limit;
  the Content-Length header is not trusted.
- On disk the file name is always a UUID; the original name is only kept as metadata
  (closes the path traversal hole, audit point 3).
- SHA-256 is computed while writing, without reading the file twice.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath

from app.core.errors import PayloadTooLarge, ValidationError
from app.services.library.model import IncomingFile

logger = logging.getLogger(__name__)

_READ_CHUNK = 1024 * 1024
_MAX_FILENAME_CHARS = 200


@dataclass(frozen=True)
class ReceivedFile:
    path: Path  # temporary file with a UUID name
    original_filename: str
    ext: str
    size_bytes: int
    sha256: str


def safe_original_filename(raw: str | None) -> str:
    """File name for display: no folders, no control characters."""
    name = PurePath((raw or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:_MAX_FILENAME_CHARS] or "document"


def file_extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


async def receive_upload(file: IncomingFile, dest_dir: Path, max_bytes: int) -> ReceivedFile:
    """Store the upload in ``dest_dir/tmp-<uuid><ext>`` while computing its hash & size.

    Raises:
        PayloadTooLarge: larger than ``max_bytes`` (the temporary file is deleted).
        ValidationError: the file is empty.
    """
    original = safe_original_filename(file.filename)
    ext = file_extension(original)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_dir / f"tmp-{uuid.uuid4().hex}{ext}"

    digest = hashlib.sha256()
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(_READ_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise PayloadTooLarge(
                        f"The file is larger than {max_bytes // (1024 * 1024)} MB.",
                        code="FILE_TOO_LARGE",
                    )
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ValidationError("The file is empty.", code="FILE_EMPTY")
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return ReceivedFile(
        path=tmp_path,
        original_filename=original,
        ext=ext,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )


def count_pages(path: Path, ext: str) -> int | None:
    """Number of PDF pages (fast, no Docling). None for Markdown.

    Raises:
        ValidationError: the PDF is broken / cannot be opened.
    """
    if ext != ".pdf":
        return None
    import pypdfium2 as pdfium  # a Docling dependency, already installed

    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception as exc:
        logger.info("Could not open the PDF (%s): %s", path.name, exc)
        raise ValidationError(
            "The PDF is broken or password-protected.", code="FILE_CORRUPT"
        ) from exc
