"""Helpers bersama untuk test Library."""
from __future__ import annotations

import io

import pypdfium2 as pdfium
from fastapi import UploadFile


def make_pdf(pages: int = 1, marker: int = 0) -> bytes:
    """PDF valid dengan jumlah halaman tertentu. `marker` membuat isi (hash) berbeda."""
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200 + marker, 200)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def upload(data: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)
