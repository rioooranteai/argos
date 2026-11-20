"""Konteks log per request / per job (DESIGN_GROUP_C.md §7.2).

Field yang dikenal: ``user_id``, ``notebook_id``, ``version_id``, ``stage``,
``message_id``. Nilainya masuk ke setiap baris log (lihat ``logging_setup``) dan
ke catatan ``llm_calls``.

Dua cara mengisi:

- ``bind_request(**fields)`` mengubah dict milik request yang sedang berjalan
  *di tempat*. Dipakai oleh dependency sinkron FastAPI (dijalankan di thread):
  contextvar yang di-``set`` di thread tidak terlihat oleh endpoint, sedangkan
  perubahan isi dict yang sama terlihat.
- ``scoped(**fields)`` membuat dict baru untuk blok ``with`` lalu
  mengembalikannya. Dipakai oleh worker dokumen (tiap task asyncio punya
  salinan konteksnya sendiri).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

FIELDS = ("user_id", "notebook_id", "version_id", "stage", "message_id")

_log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def current() -> dict[str, Any]:
    """Salinan field konteks yang terisi saat ini."""
    ctx = _log_context.get()
    return dict(ctx) if ctx else {}


def get(name: str) -> Any:
    ctx = _log_context.get()
    return ctx.get(name) if ctx else None


def start_request() -> object:
    """Dict baru untuk satu request HTTP. Dipanggil oleh middleware request ID."""
    return _log_context.set({})


def end_request(token: object) -> None:
    _log_context.reset(token)  # type: ignore[arg-type]


def bind_request(**fields: Any) -> None:
    """Isi field untuk sisa request ini (lihat docstring modul)."""
    ctx = _log_context.get()
    clean = {k: v for k, v in fields.items() if v is not None}
    if ctx is None:
        _log_context.set(clean)
    else:
        ctx.update(clean)


@contextmanager
def scoped(**fields: Any) -> Iterator[None]:
    """Field berlaku hanya di dalam blok ``with``."""
    merged = {**current(), **{k: v for k, v in fields.items() if v is not None}}
    token = _log_context.set(merged)
    try:
        yield
    finally:
        _log_context.reset(token)
