"""Helpers bersama untuk test Library."""
from __future__ import annotations

import functools
import io

import pypdfium2 as pdfium
from fastapi import UploadFile


@functools.cache
def make_pdf(pages: int = 1, marker: int = 0) -> bytes:
    """PDF valid dengan jumlah halaman tertentu. `marker` membuat isi (hash) berbeda.

    Di-cache: PDFium menulis CreationDate per detik, sehingga dua panggilan yang
    melewati batas detik akan menghasilkan hash berbeda (test jadi flaky).
    """
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200 + marker, 200)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def upload(data: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)
