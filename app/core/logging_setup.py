"""Logging configuration (DESIGN_GROUP_C.md §7.2).

``json`` format: one JSON object per line, with the fields
``ts, level, logger, msg, request_id`` + any context fields that are set
(``user_id, notebook_id, version_id, stage, message_id``) + ``duration_ms`` when
passed through ``extra``. Exceptions go into the ``exc`` field.

``text`` format is for reading in a terminal during local development: aligned
columns (local time, level, short component name, message), context fields at the
end, uvicorn access lines shown as ``METHOD path status client request_id``, and
ANSI colours when the stream is a terminal (disabled by ``NO_COLOR``).

``auto`` picks ``text`` for a terminal and ``json`` otherwise (Docker, files, pipes).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import TextIO

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


# Short component names for the text format, by logger-name prefix (first match wins).
_COMPONENTS = (
    ("uvicorn.access", "http"),
    ("uvicorn", "uvicorn"),
    ("app.tools.document_parser", "docling"),
    ("app.tools.vision", "vision"),
    ("app.tools.extraction", "extraction"),
    ("app.tools.speech", "voice"),
    ("app.services.ingestion", "ingestion"),
    ("app.tools.vector_store", "vector"),
    ("app.tools.llm", "llm"),
    ("app.tools.embedding", "embed"),
    ("app.core.observability", "observe"),
    ("app.services.extraction", "extraction"),
    ("app.services.nl2sql", "nl2sql"),
    ("app.services.voice", "voice"),
    ("app.services.library", "library"),
    ("app.services.notebook", "notebook"),
    ("app.services.conversation", "chat"),
    ("app.services.observability", "observe"),
    ("app.services.user", "admin"),
    ("app.tools.storage", "storage"),
    ("app.engines.document_engine.worker", "worker"),
    ("app.engines.document_engine", "pipeline"),
    ("app.engines.chat_engine", "chat"),
    ("app.api.routers", "api"),
    ("app.core.errors", "errors"),
    ("app.core.startup", "startup"),
    ("app.core", "core"),
)
_COMPONENT_WIDTH = 10
_LEVELS = {"WARNING": "WARN", "CRITICAL": "CRIT"}

_RESET, _DIM, _BOLD = "\033[0m", "\033[2m", "\033[1m"
_LEVEL_COLORS = {
    "DEBUG": "\033[90m", "INFO": "\033[32m", "WARNING": "\033[33m",
    "ERROR": "\033[31m", "CRITICAL": "\033[1;31m",
}
_STATUS_COLORS = {"2": "\033[32m", "3": "\033[36m", "4": "\033[33m", "5": "\033[31m"}


def _component(name: str) -> str:
    for prefix, short in _COMPONENTS:
        if name == prefix or name.startswith(prefix + "."):
            return short
    return name.rsplit(".", 1)[-1][:_COMPONENT_WIDTH]


class TextFormatter(logging.Formatter):
    """Aligned, optionally coloured lines for a terminal (see the module docstring)."""

    def __init__(self, color: bool = False) -> None:
        super().__init__()
        self._color = color

    def _paint(self, code: str, text: str) -> str:
        return f"{code}{text}{_RESET}" if self._color and code else text

    def format(self, record: logging.LogRecord) -> str:
        time = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level = _LEVELS.get(record.levelname, record.levelname)
        level = self._paint(_LEVEL_COLORS.get(record.levelname, ""), f"{level:<5}")
        component = self._paint(_BOLD, f"{_component(record.name):<{_COMPONENT_WIDTH}}")
        request_id = getattr(record, "request_id", "-")

        message = self._access_line(record, request_id)
        extras: list[str] = []
        if message is None:
            message = record.getMessage()
            if request_id and request_id != "-":
                extras.append(f"req={request_id}")
        ctx = getattr(record, "log_context", None) or {}
        extras += [f"{k}={v}" for k, v in ctx.items()]
        for name in _EXTRA_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                extras.append(f"{name}={value}")

        line = f"{self._paint(_DIM, time)}  {level}  {component}  {message}"
        if extras:
            line += " " + self._paint(_DIM, " ".join(extras))
        exc = self.formatException(record.exc_info) if record.exc_info else record.exc_text
        if exc:
            line += "\n" + "\n".join(self._paint(_DIM, "    │ ") + row for row in exc.splitlines())
        return line

    def _access_line(self, record: logging.LogRecord, request_id: str) -> str | None:
        """``GET  /login  200  127.0.0.1  <request id>`` for uvicorn access records."""
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple) or len(record.args) != 5:
            return None
        client, method, path, _http_version, status = record.args
        status = str(status)
        line = (
            f"{method:<6} {path:<40} {self._paint(_STATUS_COLORS.get(status[:1], ''), status)}  "
            f"{self._paint(_DIM, str(client).rsplit(':', 1)[0])}"
        )
        if request_id and request_id != "-":
            line += "  " + self._paint(_DIM, request_id)
        return line


def _enable_windows_ansi(stream: TextIO) -> bool:
    """Turn on ANSI escape handling in a Windows console. False if that is not possible."""
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # VIRTUAL_TERMINAL_PROCESSING
    except (ImportError, AttributeError, OSError, ValueError):
        return False


def _is_terminal(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def _use_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") or not _is_terminal(stream):
        return False
    return os.name != "nt" or _enable_windows_ansi(stream)


def configure_logging(fmt: str = "auto", level: int = logging.INFO) -> None:
    """Replace the root handlers with one stderr handler in ``fmt`` format.

    ``fmt``: ``"json"``, ``"text"``, or ``"auto"`` (text in a terminal, json otherwise).
    """
    stream = sys.stderr
    if fmt == "auto":
        fmt = "text" if _is_terminal(stream) else "json"
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter(color=_use_color(stream)))

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
