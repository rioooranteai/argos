"""Logging configuration (DESIGN_GROUP_C.md §7.2).

``json`` format: one JSON object per line, with the fields
``ts, level, logger, msg, request_id`` + any context fields that are set
(``user_id, notebook_id, version_id, stage, message_id``) + ``duration_ms`` when
passed through ``extra``. Exceptions go into the ``exc`` field.

``text`` format is for reading directly during local development.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.core import log_context
from app.core.request_context import get_request_id

_EXTRA_FIELDS = ("duration_ms",)


class ContextFilter(logging.Filter):
    """Attaches the request ID and context fields to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.log_context = log_context.current()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "-")
        if request_id and request_id != "-":
            out["request_id"] = request_id
        out.update(getattr(record, "log_context", None) or {})
        for name in _EXTRA_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                out[name] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            out["exc"] = record.exc_text
        return json.dumps(out, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s%(ctx)s")

    def format(self, record: logging.LogRecord) -> str:
        ctx = getattr(record, "log_context", None) or {}
        record.ctx = (" " + " ".join(f"{k}={v}" for k, v in ctx.items())) if ctx else ""
        return super().format(record)


def configure_logging(fmt: str = "json", level: int = logging.INFO) -> None:
    """Replace the root handlers with a single stdout handler in ``fmt`` format."""
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())

    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn access logs use their own handlers; route them to root so they use this format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
