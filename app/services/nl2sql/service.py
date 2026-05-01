import logging
import sqlite3
from pathlib import Path

from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.exceptions import InvalidQuestionError
from app.services.nl2sql.executor import execute_readonly_sql
from app.services.nl2sql.security import sanitize_nl_input, validate_generated_sql

logger = logging.getLogger(__name__)

MAX_RAW_ROWS = 100

_COLUMN_HINTS: dict[str, str] = {
    "brand_name": "The manufacturer or brand name (e.g. Toyota, Spotify, Nike). NULL if not determinable from the text.",
    "product_name": "The specific product or service variant name, excluding the brand prefix (e.g. 'Avanza 1.3E Manual', 'Premium Individual').",
    "price": "Float or NULL. Direct user-facing price as a numeric value only, no currency symbols.",
    "price_currency": "ISO 4217 currency code (e.g. USD, IDR, EUR, GBP, SGD) or NULL if no currency indicator is present near the price.",
    "advantages": "Explicit positive facts about the product stated in the text. Include exact numeric values when present. NULL if none stated.",
    "disadvantages": "Explicit negative facts about the product stated in the text. Include exact numeric values when present. NULL if none stated.",
}

_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _introspect_features_schema(db_path: Path) -> str:
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute("PRAGMA table_info(features)").fetchall()

    if not rows:
        return "-- Tabel `features` belum tersedia."

    column_lines: list[str] = []
    for _cid, name, ctype, notnull, _dflt, pk in rows:
        constraints = []
        if pk:
            constraints.append("PRIMARY KEY")
            if ctype.upper() == "INTEGER":
                constraints.append("AUTOINCREMENT")
        if notnull and not pk:
            constraints.append("NOT NULL")
        constraint_str = (" " + " ".join(constraints)) if constraints else ""
        comment = f" -- {_COLUMN_HINTS[name]}" if name in _COLUMN_HINTS else ""
        column_lines.append(f"    {name} {ctype}{constraint_str},{comment}")

    last = column_lines[-1]
    if " --" in last:
        body, _, comment = last.partition(" --")
        column_lines[-1] = body.rstrip(",") + " --" + comment
    else:
        column_lines[-1] = last.rstrip(",")

    return "CREATE TABLE features (\n" + "\n".join(column_lines) + "\n);"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file tidak ditemukan: {path}")


_SQL_PROMPT_TEXT = _load_prompt("nl2sql_generator.md")


class NL2SQLService:
    def __init__(self, llm_provider: BaseLLM, db_path: Path):
        self.llm = llm_provider
        self._db_path = db_path

    def _build_sql_prompt(self, question: str) -> str:
        schema = _introspect_features_schema(self._db_path)

        hints_text = "\n".join(
            f"- {col}: {hint}" for col, hint in _COLUMN_HINTS.items()
        )

        return (
            f"Schema database:\n{schema}\n\n"
            f"Schema database explanation:\n{hints_text}\n\n"
            f"Question: {question}"
        )

    async def process_query(self, user_question: str) -> dict:
        try:
            safe_question = sanitize_nl_input(user_question)
            sql = await self._generate_sql(safe_question)
            rows, row_count, is_truncated = self._execute_sql(sql)

            return {
                "status": "success",
                "sql_query": sql,
                "raw_data": rows,
                "row_count": row_count,
                "truncated": is_truncated
            }


        except InvalidQuestionError as e:

            return {
                "status": "error",
                "message": str(e),
                "sql_query": None,
                "raw_data": None,
                "row_count": 0,
                "truncated": False,
            }

        except ValueError as ve:
            return {"status": "error", "message": str(ve)}
        except Exception:
            logger.exception("Kesalahan tidak terduga saat memproses query NL2SQL")
            return {"status": "error", "message": "Terjadi kesalahan sistem."}

    async def _generate_sql(self, question: str) -> str:
        raw_sql = await self.llm.ainvoke(
            prompt=self._build_sql_prompt(question),
            system=_SQL_PROMPT_TEXT
        )

        logger.info(raw_sql)

        if raw_sql.strip().upper() == "INVALID_QUESTION":
            raise InvalidQuestionError(
                "Pertanyaan tidak relevan dengan database intelijen kompetitor "
                "atau tidak dapat dijawab dengan data yang tersedia."
            )

        clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()
        return validate_generated_sql(clean_sql)

    def _execute_sql(self, sql: str) -> tuple[list, int, bool]:
        query_results = execute_readonly_sql(sql, self._db_path)
        is_truncated = len(query_results) > MAX_RAW_ROWS
        limited_results = query_results[:MAX_RAW_ROWS]

        return limited_results, len(query_results), is_truncated
