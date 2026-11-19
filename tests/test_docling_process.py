"""Subprocess parser: hasil normal, error dokumen, timeout → kill & start ulang, crash."""
from __future__ import annotations

import pytest

from app.services.ingestion.exceptions import DocumentLoadError
from app.services.ingestion.providers.loaders.docling_process import (
    DoclingProcess,
    ParserTimeout,
    ParserUnavailable,
)

ECHO = "tests.fake_loaders:EchoLoader"


def _pid(elements) -> str:
    return elements[0].content.split("pid=")[1]


async def test_parse_ok_and_process_reused():
    proc = DoclingProcess(ECHO, start_timeout=60)
    try:
        a = await proc.parse("a.pdf", timeout=30)
        b = await proc.parse("b.pdf", timeout=30)
        assert a[0].content.startswith("isi a.pdf")
        assert _pid(a) == _pid(b)  # model dimuat sekali, proses dipakai ulang
    finally:
        await proc.stop()
    assert not proc.is_alive


async def test_document_error_keeps_process_alive():
    proc = DoclingProcess(ECHO, start_timeout=60)
    try:
        with pytest.raises(DocumentLoadError):
            await proc.parse("bad.pdf", timeout=30)
        assert proc.is_alive
        assert await proc.parse("ok.pdf", timeout=30)
    finally:
        await proc.stop()


async def test_timeout_kills_and_restarts():
    proc = DoclingProcess(ECHO, start_timeout=60)
    try:
        first = await proc.parse("a.pdf", timeout=30)
        with pytest.raises(ParserTimeout):
            await proc.parse("hang.pdf", timeout=0.5)
        assert not proc.is_alive
        after = await proc.parse("b.pdf", timeout=30)
        assert _pid(after) != _pid(first)
    finally:
        await proc.stop()


async def test_crash_is_transient():
    proc = DoclingProcess(ECHO, start_timeout=60)
    try:
        with pytest.raises(ParserUnavailable):
            await proc.parse("crash.pdf", timeout=30)
        assert await proc.parse("ok.pdf", timeout=30)
    finally:
        await proc.stop()


async def test_loader_init_failure():
    proc = DoclingProcess("tests.fake_loaders:BrokenLoader", start_timeout=60)
    with pytest.raises(ParserUnavailable):
        await proc.parse("a.pdf", timeout=30)
    await proc.stop()
