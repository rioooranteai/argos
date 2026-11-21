"""JSON logs + request/job context (DESIGN_GROUP_C.md §7.2)."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import log_context
from app.core.logging_setup import ContextFilter, JsonFormatter, TextFormatter
from app.core.request_context import REQUEST_ID_HEADER, RequestIDMiddleware


class _Capture(logging.Handler):
    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self.addFilter(ContextFilter())
        self.setFormatter(formatter)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _logger(formatter: logging.Formatter | None = None) -> tuple[logging.Logger, _Capture]:
    handler = _Capture(formatter or JsonFormatter())
    logger = logging.getLogger(f"test.logging.{id(handler)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, handler


def test_json_line_has_base_fields_only_when_no_context():
    logger, cap = _logger()
    logger.info("halo %s", "dunia")
    out = json.loads(cap.lines[0])
    assert out["msg"] == "halo dunia"
    assert out["level"] == "INFO"
    assert {"ts", "logger"} <= out.keys()
    assert "request_id" not in out and "user_id" not in out


def test_scoped_fields_and_duration_and_exception():
    logger, cap = _logger()
    with log_context.scoped(version_id="v1", stage="parsing"):
        try:
            raise RuntimeError("rusak")
        except RuntimeError:
            logger.exception("gagal", extra={"duration_ms": 12})
    logger.info("di luar")

    inside, outside = (json.loads(line) for line in cap.lines)
    assert inside["version_id"] == "v1" and inside["stage"] == "parsing"
    assert inside["duration_ms"] == 12
    assert "RuntimeError: rusak" in inside["exc"]
    assert "version_id" not in outside


def test_bind_request_mutates_current_scope():
    logger, cap = _logger()
    with log_context.scoped(version_id="v1"):
        log_context.bind_request(stage="vision")
        logger.info("x")
    assert json.loads(cap.lines[0])["stage"] == "vision"


def test_asyncio_tasks_do_not_leak_context_into_each_other():
    seen: dict[str, dict] = {}

    async def job(vid: str) -> None:
        with log_context.scoped(version_id=vid):
            await asyncio.sleep(0)
            log_context.bind_request(stage=f"stage-{vid}")
            await asyncio.sleep(0)
            seen[vid] = log_context.current()

    async def main() -> None:
        await asyncio.gather(job("a"), job("b"))

    asyncio.run(main())
    assert seen["a"] == {"version_id": "a", "stage": "stage-a"}
    assert seen["b"] == {"version_id": "b", "stage": "stage-b"}


def test_sync_dependency_binding_visible_in_async_endpoint():
    """A synchronous dependency runs in a thread; its fields are still visible in the endpoint."""
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    def current_user() -> str:
        log_context.bind_request(user_id="u-1")
        return "u-1"

    @app.get("/nb/{notebook_id}")
    async def endpoint(notebook_id: str, user: str = Depends(current_user)):
        log_context.bind_request(notebook_id=notebook_id)
        return log_context.current()

    client = TestClient(app)
    first = client.get("/nb/n-9", headers={REQUEST_ID_HEADER: "req-1"})
    assert first.json() == {"user_id": "u-1", "notebook_id": "n-9"}
    # The next request starts with an empty context.
    assert log_context.current() == {}


def test_text_formatter_appends_context():
    logger, cap = _logger(TextFormatter())
    with log_context.scoped(user_id="u-2"):
        logger.warning("teks")
    assert cap.lines[0].endswith("teks user_id=u-2")


def _record(name: str, msg: str, args=(), level=logging.INFO, exc_info=None) -> logging.LogRecord:
    record = logging.LogRecord(name, level, __file__, 1, msg, args, exc_info)
    record.request_id = "-"
    record.log_context = {}
    return record


def test_text_formatter_aligns_columns_without_color():
    line = TextFormatter().format(_record("app.engines.document_engine.worker", "Document worker running (2 slots)."))
    time, rest = line[:8], line[8:]
    assert time.count(":") == 2
    assert rest == "  INFO   worker      Document worker running (2 slots)."
    assert "\033[" not in line


def test_text_formatter_short_level_and_unknown_component():
    line = TextFormatter().format(_record("some.other.module", "careful", level=logging.WARNING))
    assert "  WARN   module      careful" in line


def test_text_formatter_access_line():
    record = _record("uvicorn.access", '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:56756", "GET", "/login", "1.1", 200))
    record.request_id = "43fb178816c7"
    line = TextFormatter().format(record)
    assert "  http        GET    /login" in line
    assert line.rstrip().endswith("200  127.0.0.1  43fb178816c7")


def test_text_formatter_colors_and_exception_indent():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = _record("app.core.errors", "failed", level=logging.ERROR, exc_info=sys.exc_info())
    line = TextFormatter(color=True).format(record)
    assert "\033[31mERROR" in line
    assert "    │ [0mValueError: boom" in line


def test_auto_format_is_json_when_not_a_terminal(monkeypatch):
    import io
    import sys

    from app.core import logging_setup

    monkeypatch.setattr(sys, "stderr", io.StringIO())
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        logging_setup.configure_logging("auto")
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])


def test_no_color_env_disables_color(monkeypatch):
    from app.core import logging_setup

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setenv("NO_COLOR", "1")
    assert logging_setup._use_color(Tty()) is False
