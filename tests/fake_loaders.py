"""Fake loaders for the Docling subprocess tests (must be importable by a spawned process)."""
from __future__ import annotations

import os
import time

from app.tools.document_parser.base import DocumentElement, ElementType


class EchoLoader:
    def load(self, path: str):
        if path.endswith("hang.pdf"):
            time.sleep(60)
        if path.endswith("crash.pdf"):
            os._exit(1)
        if path.endswith("bad.pdf"):
            raise ValueError("file rusak")
        return [
            DocumentElement(
                element_type=ElementType.TEXT, content=f"isi {path} pid={os.getpid()}", page_number=1
            )
        ]


class BrokenLoader:
    def __init__(self):
        raise RuntimeError("model tidak ditemukan")
