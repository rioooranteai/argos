from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.config import app_config
from app.core.llm_errors import classify_llm_error
from app.core.observability.telemetry import spans
from app.services.nl2sql.catalog import build_catalog
from app.services.nl2sql.exceptions import InvalidQuestionError
from app.services.nl2sql.executor import (
    SQLExecutionFailed,
    SQLExecutionTimeout,
    SQLRejected,
    execute_scoped_sql,
    features_schema_ddl,
)
from app.services.nl2sql.security import validate_generated_sql
from app.tools.llm.base import BaseLLM

logger = logging.getLogger(__name__)

MAX_RAW_ROWS = 100

_COLUMN_HINTS: dict[str, str] = {
    "version_id": "Source document version of the row. ALWAYS select it for row-level results (used for citations).",
    "page_number": "Page where the fact appears. ALWAYS select it for row-level results (used for citations).",
    "section_heading": "Heading of the document section the row came from.",
    "brand_name": "The company that makes, issues or provides the product (e.g. Toyota, Spotify, a bank). NULL if not determinable.",
    "product_name": "The specific product or service variant name, excluding the brand prefix (e.g. 'Avanza 1.3E Manual', 'Premium Individual').",
    "price": "Float or NULL. What a customer pays for the product, including a recurring annual/membership/subscription fee (0 = free). Numeric only.",
    "price_currency": "ISO 4217 currency code (e.g. USD, IDR, EUR, GBP, SGD) or NULL if no currency indicator is present near the price.",
    "advantages": "Explicit positive facts about the product stated in the text. Include exact numeric values when present. NULL if none stated.",
    "disadvantages": "Explicit negative facts about the product stated in the text. Include exact numeric values when present. NULL if none stated.",
    "doc": "Short alias of the source document ('D1', 'D2', ...) as named in the CATALOG. Use it to filter by document.",
}

_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {path}") from None


_SQL_PROMPT_TEXT = _load_prompt("nl2sql_generator.md")


@dataclass
class NL2SQLResult:
    """Typed NL2SQL result (replaces the old dict).

    - ``ok``    : the query succeeded and returned rows
    - ``empty`` : the query succeeded with no rows, or the question really cannot be
                  answered from the features table (``INVALID_QUESTION``)
    - ``error`` : a system failure; the code is in ``error_code`` (DESIGN_GROUP_C.md §3):
                  ``SQL_REJECTED``, ``SQL_TIMEOUT``, ``SQL_FAILED``, or an LLM_* code

    ``message`` is only for the log; it is sent neither to the user nor to the prompt.
    """

    status: Literal["ok", "empty", "error"]
    sql_query: str | None = None
    raw_data: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    message: str | None = None
    error_code: str | None = None
    invalid: bool = False  # the model answered INVALID_QUESTION
    attempts: int = 1

    @property
    def is_row_level(self) -> bool:
        """Rows can be cited per fact when they carry version_id; otherwise they are aggregates."""
        return bool(self.raw_data) and "version_id" in self.raw_data[0]


class NL2SQLService:
    def __init__(self, llm_provider: BaseLLM, db_path: Path, exec_timeout: float = 5.0):
        self.llm = llm_provider
        self._db_path = db_path
        self._exec_timeout = exec_timeout

    def _build_sql_prompt(self, question: str, catalog: str) -> str:
        # Fixed part first (schema + hints), then the per-notebook catalog, the question last:
        # the provider can reuse the cached prefix across questions.
        hints_text = "\n".join(f"- {col}: {hint}" for col, hint in _COLUMN_HINTS.items())
        return (
            f"Schema database:\n{features_schema_ddl()}\n\n"
            f"Schema database explanation:\n{hints_text}\n\n"
            f"CATALOG (products in the active documents; * = has a price):\n{catalog or '(none)'}\n\n"
            f"Question: {question}"
        )

    async def process_query(
        self, user_question: str, version_ids: list[str], doc_labels: dict[str, str] | None = None,
    ) -> NL2SQLResult:
        """Answer the question only from the rows of `version_ids` (the notebook's active sources).

        `doc_labels` (version_id → "type: title") names the documents in the CATALOG block.
        """
        if not version_ids:
            return NL2SQLResult(status="empty", message="No active sources.")
        question = user_question.strip()
        catalog = await asyncio.to_thread(
            build_catalog, self._db_path, version_ids, question, doc_labels,
            app_config.NL2SQL_CATALOG_NAMES_PER_DOC, app_config.NL2SQL_CATALOG_MAX_CHARS,
        )
        prompt = self._build_sql_prompt(question, catalog)
        result = await self._attempt(prompt, version_ids)
        for _ in range(app_config.NL2SQL_MAX_RETRIES):
            feedback = _retry_feedback(result)
            if feedback is None:
                break
            logger.info("NL2SQL: retrying (%s).", result.error_code or ("invalid" if result.invalid else "0 rows"))
            retry = await self._attempt(prompt + feedback, version_ids)
            retry.attempts = result.attempts + 1
            if _RANK[retry.status] < _RANK[result.status]:
                result = retry
                continue
            result.attempts = retry.attempts
            break
        return result

    async def _attempt(self, prompt: str, version_ids: list[str]) -> NL2SQLResult:
        sql: str | None = None
        try:
            sql = await self._generate_sql(prompt)
            with spans.span("sql.execute") as span:
                spans.set_input(span, {"sql": sql, "version_ids": version_ids})
                rows, truncated = await asyncio.to_thread(
                    execute_scoped_sql, sql, self._db_path, version_ids, self._exec_timeout, MAX_RAW_ROWS
                )
                spans.set_output(span, rows)
                spans.set_metadata(span, row_count=len(rows), truncated=truncated)
        except InvalidQuestionError as e:
            # Not a system failure: the question does not fit the structured data.
            return NL2SQLResult(status="empty", message=str(e), invalid=True)
        except SQLExecutionTimeout as e:
            logger.warning("NL2SQL: %s", e)
            return self._error("SQL_TIMEOUT", sql, e)
        except SQLExecutionFailed as e:
            logger.warning("NL2SQL execution failed: %s", e)
            return self._error("SQL_FAILED", sql, e)
        except (SQLRejected, ValueError) as e:
            # ValueError = the SELECT validator rejected the LLM output.
            logger.warning("NL2SQL rejected: %s", e)
            return self._error("SQL_REJECTED", sql, e)
        except Exception as e:
            logger.exception("NL2SQL: the LLM call failed.")
            return self._error(classify_llm_error(e), sql, e)

        return NL2SQLResult(
            status="ok" if rows else "empty",
            sql_query=sql,
            raw_data=rows,
            row_count=len(rows),
            truncated=truncated,
        )

    @staticmethod
    def _error(code: str, sql: str | None, exc: BaseException) -> NL2SQLResult:
        return NL2SQLResult(status="error", sql_query=sql, message=str(exc), error_code=code)

    async def _generate_sql(self, prompt: str) -> str:
        raw_sql = await self.llm.ainvoke(prompt=prompt, system=_SQL_PROMPT_TEXT)
        logger.debug("NL2SQL generated: %s", raw_sql)

        if raw_sql.strip().upper() == "INVALID_QUESTION":
            raise InvalidQuestionError(
                "The question is not relevant to the competitor intelligence database "
                "or cannot be answered with the available data."
            )

        clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()
        return validate_generated_sql(clean_sql)


_RANK = {"ok": 0, "empty": 1, "error": 2}
_RETRY_ERRORS = {"SQL_FAILED", "SQL_REJECTED"}  # the query itself was wrong; LLM/timeout errors are not retried


def _retry_feedback(result: NL2SQLResult) -> str | None:
    """A short note appended to the same prompt for one more attempt, or None (keep the result).

    Only for answers the model can fix: INVALID_QUESTION, a rejected/failing query, or 0 rows found
    through a text filter (a name or word that does not match the data). A query without LIKE that
    finds nothing (e.g. a price threshold) is a real answer and is kept.
    """
    if result.invalid:
        return ("\n\nYour previous answer was INVALID_QUESTION. Check the CATALOG: if its products can "
                "answer the question, write the query now; otherwise answer INVALID_QUESTION again.")
    if result.status == "error" and result.error_code in _RETRY_ERRORS:
        return (f"\n\nYour previous query failed:\n{result.sql_query}\n"
                f"Error: {(result.message or '')[:200]}\nWrite a corrected query.")
    if result.status == "empty" and result.sql_query and " like " in f" {result.sql_query.lower()} ":
        return (f"\n\nYour previous query returned 0 rows:\n{result.sql_query}\n"
                "Its text filters do not match the data. Use the CATALOG spelling of names, filter a "
                "category by doc, and do not filter on words that only describe the measure. "
                "If the data truly has no such rows, return the same query.")
    return None
