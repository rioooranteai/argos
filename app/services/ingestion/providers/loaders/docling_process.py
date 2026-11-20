"""Docling di subprocess yang bisa dihentikan paksa (DESIGN_GROUP_B.md §4).

Thread Python tidak bisa di-kill: PDF bermasalah yang membuat Docling hang akan
mengunci worker selamanya. Karena itu Docling berjalan di satu subprocess yang
hidup terus (model tetap ter-load) dan dipakai bergantian. Jika melewati batas
waktu, subprocess di-kill lalu dibuat ulang pada pemakaian berikutnya.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import multiprocessing
from multiprocessing.connection import Connection
from typing import Any

from app.services.ingestion.exceptions import DocumentLoadError, IngestionError
from app.services.ingestion.model import DocumentElement

logger = logging.getLogger(__name__)

DEFAULT_LOADER = "app.services.ingestion.providers.loaders.docling_loader:DoclingLoader"
_SPAWN = multiprocessing.get_context("spawn")  # sama di Windows & Linux


class ParserUnavailable(IngestionError):
    """Subprocess parser mati, gagal start, atau dihentikan karena timeout.
    Bersifat sementara: job boleh dicoba lagi."""


class ParserTimeout(ParserUnavailable):
    """Parsing melewati batas waktu; subprocess sudah di-kill."""


def _load_factory(spec: str) -> Any:
    module_name, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def _serve(conn: Connection, loader_spec: str) -> None:
    """Loop di dalam subprocess: terima path, kirim balik elemen dokumen."""
    try:
        loader = _load_factory(loader_spec)()
    except Exception as exc:  # noqa: BLE001 — di subprocess: error dikirim ke proses induk, yang mencatatnya
        conn.send(("fatal", f"{type(exc).__name__}: {exc}"))
        return
    conn.send(("ready", None))
    while True:
        try:
            path = conn.recv()
        except (EOFError, OSError):
            return
        if path is None:
            return
        try:
            conn.send(("ok", loader.load(path)))
        except Exception as exc:  # noqa: BLE001 — sama: dicatat oleh proses induk
            conn.send(("error", f"{type(exc).__name__}: {exc}"))


class DoclingProcess:
    def __init__(self, loader_spec: str = DEFAULT_LOADER, start_timeout: float = 300.0) -> None:
        self._loader_spec = loader_spec
        self._start_timeout = start_timeout
        self._process: multiprocessing.process.BaseProcess | None = None
        self._conn: Connection | None = None
        self._lock = asyncio.Lock()  # satu dokumen dalam satu waktu (DOCLING_CONCURRENCY=1)

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    async def start(self) -> None:
        """Mulai subprocess lebih awal (memuat model) agar upload pertama tidak lambat."""
        async with self._lock:
            await self._ensure_started()

    async def parse(self, path: str, timeout: float) -> list[DocumentElement]:
        async with self._lock:
            await self._ensure_started()
            assert self._conn is not None
            self._conn.send(path)
            ready = await asyncio.to_thread(self._conn.poll, timeout)
            if not ready:
                logger.warning("Docling melewati batas %.0f dtk untuk %s; subprocess di-kill.", timeout, path)
                self._kill()
                raise ParserTimeout(f"Parsing melewati batas {timeout:.0f} detik.")
            try:
                kind, payload = self._conn.recv()
            except (EOFError, OSError):
                self._kill()
                raise ParserUnavailable("Subprocess Docling berhenti tiba-tiba.") from None
            if kind == "error":
                raise DocumentLoadError(path, payload)
            return payload

    async def stop(self) -> None:
        if self._process is None:
            return
        try:
            if self._conn is not None:
                self._conn.send(None)
        except (BrokenPipeError, OSError):
            pass
        await asyncio.to_thread(self._process.join, 5)
        self._kill()

    # ── Internal ───────────────────────────────────────────────────────

    async def _ensure_started(self) -> None:
        if self.is_alive:
            return
        self._kill()
        parent, child = _SPAWN.Pipe()
        process = _SPAWN.Process(
            target=_serve, args=(child, self._loader_spec), name="docling-parser", daemon=True
        )
        process.start()
        child.close()
        self._process, self._conn = process, parent
        logger.info("Subprocess Docling dimulai (pid %s), memuat model...", process.pid)

        ready = await asyncio.to_thread(parent.poll, self._start_timeout)
        if not ready:
            self._kill()
            raise ParserUnavailable("Subprocess Docling tidak siap dalam batas waktu.")
        try:
            kind, payload = parent.recv()
        except (EOFError, OSError):
            self._kill()
            raise ParserUnavailable("Subprocess Docling gagal start.") from None
        if kind != "ready":
            self._kill()
            raise ParserUnavailable(f"Subprocess Docling gagal memuat model: {payload}")
        logger.info("Subprocess Docling siap.")

    def _kill(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._process.kill()
            self._process.join(5)
        if self._conn is not None:
            self._conn.close()
        self._process, self._conn = None, None
