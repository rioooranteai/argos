"""Log JSON + konteks request/job (DESIGN_GROUP_C.md §7.2)."""
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
    """Dependency sinkron berjalan di thread; field-nya tetap terlihat di endpoint."""
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
    # Request berikutnya mulai dengan konteks kosong.
    assert log_context.current() == {}


def test_text_formatter_appends_context():
    logger, cap = _logger(TextFormatter())
    with log_context.scoped(user_id="u-2"):
        logger.warning("teks")
    assert cap.lines[0].endswith("teks user_id=u-2")
