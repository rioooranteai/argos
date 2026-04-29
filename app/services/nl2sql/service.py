import logging
from pathlib import Path

from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.executor import execute_readonly_sql
from app.services.nl2sql.exceptions import InvalidQuestionError
from app.services.nl2sql.security import sanitize_nl_input, validate_generated_sql

logger = logging.getLogger(__name__)

MAX_RAW_ROWS = 100

TABLE_SCHEMA = """
CREATE TABLE features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  TEXT NOT NULL,
    competitor_name TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    price REAL, -- float atau NULL. Harga dalam USD.
    advantages TEXT, -- Kelebihan, metrik positif
    disadvantages TEXT -- Kelemahan, metrik menurun
);
"""

_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file tidak ditemukan: {path}")


_SQL_PROMPT_TEXT = _load_prompt("nl2sql_generator.md")
_ANSWER_PROMPT_TEXT = _load_prompt("nl2sql_answer.md")


class NL2SQLService:
    def __init__(self, llm_provider: BaseLLM, db_path: Path):
        """
        Inisialisasi service menggunakan Dependency Injection.

        Args:
            llm_provider: Implementasi BaseLLM (OpenAI, Anthropic, lokal, dll).
            db_path: Path ke SQLite database. Service tidak hardcode lokasinya
                lagi sehingga mudah dipindah / di-test dengan DB temporer.
        """
        self.llm = llm_provider
        self._db_path = db_path

    def _build_sql_prompt(self, question: str) -> str:
        """Sisipkan schema ke dalam pertanyaan user sebelum dikirim ke LLM."""
        return (
            f"Schema database:\n{TABLE_SCHEMA}\n\n"
            f"Pertanyaan: {question}"
        )

    async def process_query(self, user_question: str) -> dict:
        try:
            safe_question = sanitize_nl_input(user_question)
            sql = await self._generate_sql(safe_question)
            rows, row_count, is_truncated = self._execute_sql(sql)
            final_answer = await self._generate_answer(safe_question, rows)

            return {
                "status": "success",
                "sql_query": sql,
                "raw_data": rows,
                "row_count": row_count,
                "truncated": is_truncated,
                "answer": final_answer
            }

        except InvalidQuestionError as e:
            return {
                "status": "success",
                "answer": str(e),
                "sql_query": None,
                "raw_data": None
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

    async def _generate_answer(self, question: str, rows: list) -> str:
        final_answer = await self.llm.ainvoke(
            prompt=f"Pertanyaan: {question}\nData SQL: {rows}",
            system=_ANSWER_PROMPT_TEXT
        )

        return final_answer
