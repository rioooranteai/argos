"""Shared helpers for the Library tests."""
from __future__ import annotations

import functools
import io

import pypdfium2 as pdfium
from fastapi import UploadFile


@functools.cache
def make_pdf(pages: int = 1, marker: int = 0) -> bytes:
    """A valid PDF with a given page count. `marker` makes the content (hash) differ.

    Cached: PDFium writes CreationDate per second, so two calls that cross a
    second boundary would produce different hashes (making tests flaky).
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
