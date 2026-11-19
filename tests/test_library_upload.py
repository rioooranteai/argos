"""Penerimaan file upload: batas ukuran, hash, nama UUID, hitung halaman."""
from __future__ import annotations

import hashlib

import pytest

from app.core.errors import PayloadTooLarge, ValidationError
from app.services.library.upload import count_pages, receive_upload, safe_original_filename
from tests.library_helpers import make_pdf, upload


async def test_hash_size_and_uuid_name(tmp_path):
    data = b"# Judul\n\nisi dokumen"
    got = await receive_upload(upload(data, "catatan.md"), tmp_path, max_bytes=1024)
    assert got.sha256 == hashlib.sha256(data).hexdigest()
    assert got.size_bytes == len(data)
    assert got.path.parent == tmp_path
    assert got.path.name.startswith("tmp-") and got.path.suffix == ".md"
    assert "catatan" not in got.path.name
    assert got.path.read_bytes() == data


async def test_too_large_rejected_and_cleaned_up(tmp_path):
    with pytest.raises(PayloadTooLarge):
        await receive_upload(upload(b"x" * 2048, "big.md"), tmp_path, max_bytes=1024)
    assert list(tmp_path.iterdir()) == []


async def test_empty_file_rejected(tmp_path):
    with pytest.raises(ValidationError):
        await receive_upload(upload(b"", "empty.md"), tmp_path, max_bytes=1024)
    assert list(tmp_path.iterdir()) == []


async def test_path_traversal_name_never_used_on_disk(tmp_path):
    got = await receive_upload(upload(b"abc", "../../app/main.md"), tmp_path / "q", max_bytes=1024)
    assert got.path.parent == tmp_path / "q"
    assert got.original_filename == "main.md"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("..\\..\\evil.pdf", "evil.pdf"),
        ("/etc/passwd", "passwd"),
        ("a\x00b.pdf", "ab.pdf"),
        ("", "dokumen"),
        (None, "dokumen"),
    ],
)
def test_safe_original_filename(raw, expected):
    assert safe_original_filename(raw) == expected


def test_count_pages(tmp_path):
    path = tmp_path / "x.pdf"
    path.write_bytes(make_pdf(pages=3))
    assert count_pages(path, ".pdf") == 3


def test_count_pages_markdown_is_none(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("halo")
    assert count_pages(path, ".md") is None


def test_corrupt_pdf(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(ValidationError) as e:
        count_pages(path, ".pdf")
    assert e.value.code == "FILE_CORRUPT"
