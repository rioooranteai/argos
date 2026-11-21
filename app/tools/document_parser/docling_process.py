"""Docling in a subprocess that can be force-stopped (DESIGN_GROUP_B.md §4).

A Python thread cannot be killed: a bad PDF that makes Docling hang would lock
the worker forever. So Docling runs in one long-lived subprocess (the models stay
loaded) that is used in turn. When it goes over the time limit, the subprocess is
killed and recreated on the next use.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import multiprocessing
from multiprocessing.connection import Connection
from typing import Any

from app.tools.document_parser.base import (
    BaseDocumentParser,
    DocumentElement,
    DocumentLoadError,
    ParserTimeout,
    ParserUnavailable,
)

logger = logging.getLogger(__name__)

DEFAULT_LOADER = "app.tools.document_parser.docling_loader:DoclingLoader"
_SPAWN = multiprocessing.get_context("spawn")  # same on Windows & Linux


def _load_factory(spec: str) -> Any:
    module_name, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def _serve(conn: Connection, loader_spec: str) -> None:
    """Loop inside the subprocess: receive a path, send back the document elements."""
    try:
        loader = _load_factory(loader_spec)()
    except Exception as exc:  # noqa: BLE001 — in the subprocess: the error is sent to the parent process, which logs it
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
        except Exception as exc:  # noqa: BLE001 — same: logged by the parent process
            conn.send(("error", f"{type(exc).__name__}: {exc}"))


class DoclingProcess(BaseDocumentParser):
    def __init__(self, loader_spec: str = DEFAULT_LOADER, start_timeout: float = 300.0) -> None:
        self._loader_spec = loader_spec
        self._start_timeout = start_timeout
        self._process: multiprocessing.process.BaseProcess | None = None
        self._conn: Connection | None = None
        self._lock = asyncio.Lock()  # one document at a time (DOCLING_CONCURRENCY=1)

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    async def start(self) -> None:
        """Start the subprocess early (loading the models) so the first upload is not slow."""
        async with self._lock:
            await self._ensure_started()

    async def parse(self, path: str, timeout: float) -> list[DocumentElement]:
        async with self._lock:
            await self._ensure_started()
            assert self._conn is not None
            self._conn.send(path)
            ready = await asyncio.to_thread(self._conn.poll, timeout)
            if not ready:
                logger.warning("Docling went over the %.0f s limit for %s; subprocess killed.", timeout, path)
                self._kill()
                raise ParserTimeout(f"Parsing went over the {timeout:.0f}-second limit.")
            try:
                kind, payload = self._conn.recv()
            except (EOFError, OSError):
                self._kill()
                raise ParserUnavailable("The Docling subprocess stopped unexpectedly.") from None
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
        logger.info("Docling subprocess started (pid %s), loading models...", process.pid)

        ready = await asyncio.to_thread(parent.poll, self._start_timeout)
        if not ready:
            self._kill()
            raise ParserUnavailable("The Docling subprocess was not ready in time.")
        try:
            kind, payload = parent.recv()
        except (EOFError, OSError):
            self._kill()
            raise ParserUnavailable("The Docling subprocess failed to start.") from None
        if kind != "ready":
            self._kill()
            raise ParserUnavailable(f"The Docling subprocess failed to load the models: {payload}")
        logger.info("Docling subprocess ready.")

    def _kill(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._process.kill()
            self._process.join(5)
        if self._conn is not None:
            self._conn.close()
        self._process, self._conn = None, None
