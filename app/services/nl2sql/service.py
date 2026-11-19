from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.exceptions import InvalidQuestionError
from app.services.nl2sql.executor import (
    SQLExecutionTimeout,
    execute_scoped_sql,
    features_schema_ddl,
)
from app.services.nl2sql.security import sanitize_nl_input, validate_generated_sql

logger = logging.getLogger(__name__)

MAX_RAW_ROWS = 100

_COLUMN_HINTS: dict[str, str] = {
    "version_id": "Source document version of the row. ALWAYS select it for row-level results (used for citations).",
    "page_number": "Page where the fact appears. ALWAYS select it for row-level results (used for citations).",
    "section_heading": "Heading of the document section the row came from.",
    "brand_name": "The manufacturer or brand name (e.g. Toyota, Spotify, Nike). NULL if not determinable from the text.",
    "product_name": "The specific product or service variant name, excluding the brand prefix (e.g. 'Avanza 1.3E Manual', 'Premium Individual').",
    "price": "Float or NULL. Direct user-facing price as a numeric value only, no currency symbols.",
    "price_currency": "ISO 4217 currency code (e.g. USD, IDR, EUR, GBP, SGD) or NULL if no currency indicator is present near the price.",
    "advantages": "Explicit positive facts about the product stated in the text. Include exact numeric values when present. NULL if none stated.",
    "disadvantages": "Explicit negative facts about the product stated in the text. Include exact numeric values when present. NULL if none stated.",
}

_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file tidak ditemukan: {path}") from None


_SQL_PROMPT_TEXT = _load_prompt("nl2sql_generator.md")


@dataclass
class NL2SQLResult:
    """Hasil NL2SQL bertipe (menggantikan dict).

    - ``ok``    : query berhasil dan ada baris
    - ``empty`` : query berhasil, memang tidak ada data
    - ``error`` : pertanyaan ditolak / SQL tidak valid / gagal dieksekusi
    """

    status: Literal["ok", "empty", "error"]
    sql_query: str | None = None
    raw_data: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    message: str | None = None

    @property
    def is_row_level(self) -> bool:
        """Baris bisa disitasi per fakta bila membawa version_id; selain itu agregat."""
        return bool(self.raw_data) and "version_id" in self.raw_data[0]


class NL2SQLService:
    def __init__(self, llm_provider: BaseLLM, db_path: Path, exec_timeout: float = 5.0):
        self.llm = llm_provider
        self._db_path = db_path
        self._exec_timeout = exec_timeout

    def _build_sql_prompt(self, question: str) -> str:
        hints_text = "\n".join(f"- {col}: {hint}" for col, hint in _COLUMN_HINTS.items())
        return (
            f"Schema database:\n{features_schema_ddl()}\n\n"
            f"Schema database explanation:\n{hints_text}\n\n"
            f"Question: {question}"
        )

    async def process_query(self, user_question: str, version_ids: list[str]) -> NL2SQLResult:
        """Jawab pertanyaan hanya dari baris milik `version_ids` (sumber aktif notebook)."""
        if not version_ids:
            return NL2SQLResult(status="empty", message="Tidak ada sumber aktif.")
        try:
            safe_question = sanitize_nl_input(user_question)
            sql = await self._generate_sql(safe_question)
            rows, truncated = await asyncio.to_thread(
                execute_scoped_sql, sql, self._db_path, version_ids, self._exec_timeout, MAX_RAW_ROWS
            )
        except InvalidQuestionError as e:
            return NL2SQLResult(status="error", message=str(e))
        except SQLExecutionTimeout as e:
            logger.warning("NL2SQL: %s", e)
            return NL2SQLResult(status="error", message=str(e))
        except ValueError as e:
            logger.info("NL2SQL ditolak: %s", e)
            return NL2SQLResult(status="error", message=str(e))

        return NL2SQLResult(
            status="ok" if rows else "empty",
            sql_query=sql,
            raw_data=rows,
            row_count=len(rows),
            truncated=truncated,
        )

    async def _generate_sql(self, question: str) -> str:
        raw_sql = await self.llm.ainvoke(prompt=self._build_sql_prompt(question), system=_SQL_PROMPT_TEXT)
        logger.debug("NL2SQL generated: %s", raw_sql)

        if raw_sql.strip().upper() == "INVALID_QUESTION":
            raise InvalidQuestionError(
                "Pertanyaan tidak relevan dengan database intelijen kompetitor "
                "atau tidak dapat dijawab dengan data yang tersedia."
            )

        clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()
        return validate_generated_sql(clean_sql)
