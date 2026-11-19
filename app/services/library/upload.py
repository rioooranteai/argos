"""Penerimaan file upload yang aman (DESIGN_GROUP_B.md §8).

- File dibaca bertahap (1 MB) dan dihentikan begitu melewati batas ukuran;
  header Content-Length tidak dipercaya.
- Nama file di disk selalu UUID; nama asli hanya disimpan sebagai metadata
  (menutup celah path traversal, audit poin 3).
- SHA-256 dihitung sambil menulis, tanpa membaca file dua kali.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath

from fastapi import UploadFile

from app.core.errors import PayloadTooLarge, ValidationError

logger = logging.getLogger(__name__)

_READ_CHUNK = 1024 * 1024
_MAX_FILENAME_CHARS = 200


@dataclass(frozen=True)
class ReceivedFile:
    path: Path  # file sementara bernama UUID
    original_filename: str
    ext: str
    size_bytes: int
    sha256: str


def safe_original_filename(raw: str | None) -> str:
    """Nama file untuk ditampilkan: tanpa folder, tanpa karakter kontrol."""
    name = PurePath((raw or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:_MAX_FILENAME_CHARS] or "dokumen"


def file_extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


async def receive_upload(file: UploadFile, dest_dir: Path, max_bytes: int) -> ReceivedFile:
    """Simpan upload ke ``dest_dir/tmp-<uuid><ext>`` sambil menghitung hash & ukuran.

    Raises:
        PayloadTooLarge: ukuran melebihi ``max_bytes`` (file sementara dihapus).
        ValidationError: file kosong.
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
                        f"File melebihi {max_bytes // (1024 * 1024)} MB.",
                        code="FILE_TOO_LARGE",
                    )
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ValidationError("File kosong.", code="FILE_EMPTY")
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
    """Jumlah halaman PDF (cepat, tanpa Docling). None untuk Markdown.

    Raises:
        ValidationError: PDF rusak / tidak bisa dibuka.
    """
    if ext != ".pdf":
        return None
    import pypdfium2 as pdfium  # dependensi Docling, sudah terpasang

    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception as exc:
        logger.info("PDF tidak bisa dibuka (%s): %s", path.name, exc)
        raise ValidationError(
            "File PDF rusak atau terkunci kata sandi.", code="FILE_CORRUPT"
        ) from None
